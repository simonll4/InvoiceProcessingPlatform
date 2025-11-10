import json
import os
import sys
from pathlib import Path

import typer
from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from services.pipeline.datasets.donut_loader import download_donut_samples
from services.pipeline.service.pipeline import run_pipeline


app = typer.Typer(help="Herramientas de extracción de facturas")


@app.command()
def extract(
    path: Path = typer.Argument(..., exists=True, readable=True, help="Archivo a procesar"),
    out: Path = typer.Option(Path("out.json"), help="Archivo JSON de salida"),
) -> None:
    """Procesa un archivo individual y guarda el resultado."""
    try:
        data = run_pipeline(str(path))
    except Exception as exc:  # noqa: BLE001
        logger.exception("Pipeline error")
        raise typer.Exit(code=1) from exc

    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    typer.echo(f"Resultado guardado en {out}")


@app.command()
def batch(
    folder: Path = typer.Argument(..., exists=True, file_okay=False, help="Carpeta con documentos"),
    pattern: str = typer.Option("*", help="Patrón glob para filtrar archivos"),
    save: bool = typer.Option(True, help="Guardar JSON por archivo procesado"),
) -> None:
    """Procesa múltiples documentos en lote."""
    files = sorted(folder.glob(pattern))
    if not files:
        typer.echo("No se encontraron archivos a procesar")
        raise typer.Exit(code=1)

    summary: list[dict] = []
    for file in files:
        typer.echo(f"Procesando {file.name}...")
        try:
            data = run_pipeline(str(file))
            summary.append({"file": str(file), "status": "success"})
            if save:
                target = file.with_suffix(".json")
                target.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            typer.echo(f"  ❌ Error: {exc}", err=True)
            summary.append({"file": str(file), "status": "error", "error": str(exc)})

    typer.echo("\nResumen:")
    for item in summary:
        status = "✅" if item["status"] == "success" else "❌"
        typer.echo(f"{status} {item['file']}")


@app.command()
def fetch_donut(
    split: str = typer.Option("train", help="Split del dataset"),
    limit: int = typer.Option(10, min=1, help="Cantidad de muestras"),
    out_dir: Path = typer.Option(Path("datasets/donut_samples"), help="Directorio de salida"),
) -> None:
    """Descarga un subconjunto pequeño del dataset Donut para pruebas locales."""
    try:
        paths = download_donut_samples(out_dir=str(out_dir), split=split, limit=limit)
        typer.echo(f"Descargadas {len(paths)} muestras en {out_dir}")
    except Exception as exc:  # noqa: BLE001
        typer.echo(f"Error descargando dataset: {exc}", err=True)
        raise typer.Exit(code=1) from exc


@app.command()
def test_samples() -> None:
    """Ejecuta el pipeline sobre la primera muestra encontrada en datasets/."""
    datasets_dir = PROJECT_ROOT / "datasets"
    if not datasets_dir.exists():
        typer.echo("No se encontró la carpeta datasets/")
        raise typer.Exit(code=1)

    candidates = list(datasets_dir.rglob("*.pdf")) + list(datasets_dir.rglob("*.png"))
    if not candidates:
        typer.echo("No hay samples disponibles para probar")
        raise typer.Exit(code=1)

    sample = candidates[0]
    typer.echo(f"Probando con {sample}")
    data = run_pipeline(str(sample))
    typer.echo(json.dumps(data, indent=2, ensure_ascii=False))


def main() -> None:
    logger.remove()
    logger.add(sys.stderr, level=os.getenv("LOG_LEVEL", "INFO"))
    app()


if __name__ == "__main__":
    main()
