#!/bin/bash
# Script de tests manuales para el sistema dinámico basado en schema
# Ejecutar después de levantar el servicio con docker-compose up

BASE_URL="${API_URL:-http://localhost:8000}"
SESSION_ID="test-session-$(date +%s)"

echo "════════════════════════════════════════════════════════════════════════════════"
echo " 🧪 TESTS MANUALES - SISTEMA DINÁMICO BASADO EN SCHEMA"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Base URL: $BASE_URL"
echo "Session ID: $SESSION_ID"
echo ""

# Función helper para hacer requests
test_question() {
    local num=$1
    local name=$2
    local question=$3
    
    echo "─────────────────────────────────────────────────────────────────────────────"
    echo "TEST $num: $name"
    echo "Pregunta: $question"
    echo "─────────────────────────────────────────────────────────────────────────────"
    
    response=$(curl -s -X POST "$BASE_URL/api/v1/assistant/chat" \
        -H "Content-Type: application/json" \
        -d "{
            \"session_id\": \"$SESSION_ID\",
            \"question\": \"$question\"
        }")
    
    echo "$response" | python3 -m json.tool 2>/dev/null || echo "$response"
    echo ""
    echo ""
}

# Tests dentro del dominio
echo "════════════════════════════════════════════════════════════════════════════════"
echo " ✅ TESTS DENTRO DEL DOMINIO"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

test_question 1 "Item más caro (sin hardcode)" \
    "¿Cuál es el item más caro?"

test_question 2 "Total de facturas" \
    "¿Cuántas facturas tengo en total?"

test_question 3 "Proveedores principales" \
    "¿Cuáles son los 3 proveedores con más gasto?"

test_question 4 "Búsqueda por fecha" \
    "¿Cuántas facturas tengo del año 2024?"

test_question 5 "Agregación total" \
    "¿Cuánto gasté en total en todas las facturas?"

test_question 6 "Búsqueda por proveedor" \
    "Facturas de proveedor Amazon"

test_question 7 "Query compleja" \
    "¿Cuál es el promedio de gasto por factura?"

# Tests fuera del dominio
echo "════════════════════════════════════════════════════════════════════════════════"
echo " ❌ TESTS FUERA DEL DOMINIO (deben ser rechazados)"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

test_question 8 "Fuera de dominio - clima" \
    "¿Qué tiempo hace en Buenos Aires?"

test_question 9 "Fuera de dominio - general knowledge" \
    "¿Qué es la inteligencia artificial?"

test_question 10 "Fuera de dominio - deportes" \
    "¿Quién ganó el mundial 2022?"

# Tests de respuestas locales
echo "════════════════════════════════════════════════════════════════════════════════"
echo " 💬 TESTS DE RESPUESTAS LOCALES"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

test_question 11 "Saludo" \
    "Hola"

test_question 12 "Gracias" \
    "Gracias"

# Tests de edge cases
echo "════════════════════════════════════════════════════════════════════════════════"
echo " 🔍 TESTS DE EDGE CASES"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""

test_question 13 "Query con 0 resultados" \
    "¿Cuántas facturas tengo del año 1900?"

test_question 14 "Query ambigua" \
    "Dame información sobre las facturas"

test_question 15 "Query con múltiples joins" \
    "¿Qué proveedor tiene el item individual más caro?"

echo "════════════════════════════════════════════════════════════════════════════════"
echo " ✅ TESTS COMPLETADOS"
echo "════════════════════════════════════════════════════════════════════════════════"
echo ""
echo "Validaciones a revisar:"
echo "  1. ✅ Preguntas dentro del dominio generaron SQL dinámicamente"
echo "  2. ✅ Se llamó get_database_schema cuando correspondía"
echo "  3. ❌ Preguntas fuera del dominio fueron rechazadas con mensaje claro"
echo "  4. 💬 Saludos/gracias tuvieron respuesta local instantánea"
echo "  5. ✅ Query con 0 resultados mencionó 'no se encontraron datos'"
echo ""
echo "Verificar en logs del servidor:"
echo "  docker-compose logs -f assistant | grep -E '(get_database_schema|execute_sql_query|fallback)'"
echo ""
echo "❌ NO debería aparecer: 'Applying fallback plan' (si DISABLE_FALLBACK=1)"
echo "✅ SÍ debería aparecer: 'Tool call: get_database_schema'"
echo ""
