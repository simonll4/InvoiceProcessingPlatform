// Tab switching
function switchTab(tabName) {
    // Update tabs
    document.querySelectorAll('.tab').forEach(tab => tab.classList.remove('active'));
    event.target.classList.add('active');

    // Update content
    document.querySelectorAll('.tab-content').forEach(content => content.classList.remove('active'));
    document.getElementById(tabName + '-tab').classList.add('active');
}

// Pipeline Tab Logic
const uploadArea = document.getElementById('uploadArea');
const fileInput = document.getElementById('fileInput');
const processing = document.getElementById('processing');
const result = document.getElementById('result');
const error = document.getElementById('error');

uploadArea.addEventListener('click', () => fileInput.click());

uploadArea.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadArea.classList.add('dragover');
});

uploadArea.addEventListener('dragleave', () => {
    uploadArea.classList.remove('dragover');
});

uploadArea.addEventListener('drop', (e) => {
    e.preventDefault();
    uploadArea.classList.remove('dragover');
    const file = e.dataTransfer.files[0];
    if (file) processFile(file);
});

fileInput.addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (file) processFile(file);
});

async function processFile(file) {
    // Hide previous results
    result.style.display = 'none';
    error.style.display = 'none';
    processing.style.display = 'block';

    const formData = new FormData();
    formData.append('file', file);

    try {
        const response = await fetch('/api/pipeline/extract', {
            method: 'POST',
            body: formData
        });

        const contentType = response.headers.get('content-type') || '';
        let data = null;
        let fallbackText = '';

        if (contentType.includes('application/json')) {
            data = await response.json();
        } else {
            fallbackText = (await response.text()).slice(0, 400);
        }

        if (!response.ok) {
            let errorMsg = data?.detail || fallbackText || 'Error processing file';
            
            // Mensajes más amigables para errores comunes
            if (response.status === 500 && errorMsg.includes('Límite de peticiones')) {
                errorMsg = '⏱️ Límite de API alcanzado. Espera 1-2 minutos e intenta nuevamente.';
            } else if (response.status === 500 && errorMsg.includes('rate limit')) {
                errorMsg = '⏱️ Límite de API alcanzado. Espera 1-2 minutos e intenta nuevamente.';
            } else if (errorMsg.includes('LLM returned')) {
                errorMsg = '⚠️ El documento tiene muy poco texto legible. Intenta con una imagen más clara o un PDF con más contenido.';
            } else if (fallbackText.includes('Request Entity Too Large')) {
                errorMsg = '📄 El archivo supera el tamaño permitido. Intenta con un PDF/imagen más liviano o reduce su resolución.';
            }
            
            throw new Error(errorMsg);
        }

        if (!data) {
            throw new Error('El servidor no devolvió una respuesta JSON válida. Intenta nuevamente en unos segundos.');
        }

        displayResult(data);
    } catch (err) {
        console.error('Pipeline request failed', err);
        error.textContent = err.message;
        error.style.display = 'block';
    } finally {
        processing.style.display = 'none';
    }
}

function displayResult(data) {
    const grid = document.getElementById('resultGrid');
    grid.innerHTML = '';

    const invoice = data.invoice || {};
    const items = Array.isArray(data.items) ? data.items : [];
    const notes = data.notes || {};

    // Summary Section
    const summaryFields = [
        { label: 'Proveedor', value: invoice.vendor_name },
        { label: 'Número', value: invoice.invoice_number },
        { label: 'Fecha', value: invoice.invoice_date },
        { label: 'Moneda', value: invoice.currency_code || 'UNK' },
        { label: 'Items', value: items.length },
        { label: 'Confianza', value: formatConfidence(notes.confidence) },
    ];
    grid.appendChild(createStatSection('📋 Resumen', summaryFields));

    // Parties
    const partiesSection = document.createElement('div');
    partiesSection.className = 'result-section';
    partiesSection.innerHTML = `
        <div class="section-title">👥 Participantes</div>
        <div class="party-grid">
            ${createPartyCard('Proveedor', invoice.vendor_name, invoice.vendor_tax_id)}
            ${createPartyCard('Cliente', invoice.buyer_name, invoice.buyer_tax_id)}
        </div>
    `;
    grid.appendChild(partiesSection);

    // Amounts
    const amountFields = [
        { label: 'Subtotal', value: formatCurrency(invoice.subtotal_cents, invoice.currency_code) },
        { label: 'Descuento', value: formatCurrency(invoice.discount_cents, invoice.currency_code) },
        { label: 'Impuestos / Fees', value: formatCurrency(invoice.tax_cents, invoice.currency_code) },
        { label: 'Total', value: formatCurrency(invoice.total_cents, invoice.currency_code) },
    ];
    grid.appendChild(createStatSection('💵 Totales', amountFields));

    // Items table
    if (items.length > 0) {
        const itemsSection = document.createElement('div');
        itemsSection.className = 'result-section';
        itemsSection.innerHTML = `
            <div class="section-title">🧾 Items (${items.length})</div>
            <div class="table-wrapper">
                <table class="items-table">
                    <thead>
                        <tr>
                            <th>#</th>
                            <th>Descripción</th>
                            <th>Cantidad</th>
                            <th>Precio Unitario</th>
                            <th>Total Línea</th>
                        </tr>
                    </thead>
                    <tbody>
                        ${items
                            .map(
                                (item) => `
                                    <tr>
                                        <td>${escapeHtml(item.idx ?? '-')}</td>
                                        <td>
                                            ${escapeHtml(item.description) || 'Sin descripción'}
                                            ${
                                                item.category
                                                    ? `<span class="category-tag">${escapeHtml(item.category)}</span>`
                                                    : ''
                                            }
                                        </td>
                                        <td>${formatQuantity(item.qty)}</td>
                                        <td>${formatCurrency(item.unit_price_cents, invoice.currency_code)}</td>
                                        <td>${formatCurrency(item.line_total_cents, invoice.currency_code)}</td>
                                    </tr>
                                `
                            )
                            .join('')}
                    </tbody>
                </table>
            </div>
        `;
        grid.appendChild(itemsSection);
    }

    // Warnings & confidence
    const warnings = Array.isArray(notes.warnings) ? notes.warnings : [];
    const warningsSection = document.createElement('div');
    warningsSection.className = 'result-section';
    warningsSection.innerHTML = `
        <div class="section-title">⚠️ Alertas y calidad de datos</div>
        <div class="summary-grid">
            <div class="stat-card">
                <div class="result-label">Nivel de confianza</div>
                <div class="result-value">${formatConfidence(notes.confidence)}</div>
            </div>
            <div class="stat-card">
                <div class="result-label">Advertencias detectadas</div>
                <div class="result-value">${warnings.length}</div>
            </div>
        </div>
        <ul class="warning-list">
            ${
                warnings.length
                    ? warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join('')
                    : '<li>Sin advertencias detectadas.</li>'
            }
        </ul>
    `;
    grid.appendChild(warningsSection);

    // Raw JSON
    const rawSection = document.createElement('div');
    rawSection.className = 'result-section';
    rawSection.innerHTML = `
        <div class="section-title">📦 JSON completo</div>
        <pre class="code-block">${escapeHtml(JSON.stringify(data, null, 2))}</pre>
    `;
    grid.appendChild(rawSection);

    result.style.display = 'block';
}

function createStatSection(title, fields) {
    const section = document.createElement('div');
    section.className = 'result-section';
    section.innerHTML = `
        <div class="section-title">${escapeHtml(title)}</div>
        <div class="summary-grid">
            ${fields
                .map(
                    (field) => `
                        <div class="stat-card">
                            <div class="result-label">${escapeHtml(field.label)}</div>
                            <div class="result-value">${escapeHtml(field.value ?? 'N/A')}</div>
                        </div>
                    `
                )
                .join('')}
        </div>
    `;
    return section;
}

function formatCurrency(cents, currency) {
    if (cents === null || cents === undefined || isNaN(Number(cents))) {
        return 'N/A';
    }
    const amount = Number(cents) / 100;
    return `${escapeHtml(currency || 'UNK')} ${amount.toLocaleString('es-ES', {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
    })}`;
}

function formatQuantity(value) {
    if (value === null || value === undefined || isNaN(Number(value))) return '—';
    const num = Number(value);
    return num % 1 === 0 ? num.toString() : num.toFixed(2);
}

function formatConfidence(value) {
    if (value === null || value === undefined || isNaN(Number(value))) return 'N/A';
    return `${Math.round(Number(value) * 100)}%`;
}

function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function createPartyCard(title, name, taxId) {
    return `
        <div class="party-card">
            <h4>${escapeHtml(title)}</h4>
            <p>${escapeHtml(name) || 'N/A'}</p>
            <span>Tax ID: ${escapeHtml(taxId) || '—'}</span>
        </div>
    `;
}

// Chat Tab Logic
const chatMessages = document.getElementById('chatMessages');
const chatInput = document.getElementById('chatInput');
const sendButton = document.getElementById('sendButton');
const sessionIdDisplay = document.getElementById('sessionIdDisplay');

// Generate session ID on page load (changes on reload)
let sessionId = 'session-' + Date.now() + '-' + Math.random().toString(36).substr(2, 9);
console.log('Chat session started:', sessionId);

// Update session ID display
if (sessionIdDisplay) {
    sessionIdDisplay.textContent = sessionId;
}

chatInput.addEventListener('input', function() {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 120) + 'px';
});

function handleChatKeyDown(event) {
    if (event.key === 'Enter' && !event.shiftKey) {
        event.preventDefault();
        sendMessage();
    }
}

function askQuestion(question) {
    chatInput.value = question;
    sendMessage();
}

async function sendMessage() {
    const message = chatInput.value.trim();
    if (!message) return;

    // Add user message
    addMessage('user', message);
    chatInput.value = '';
    chatInput.style.height = 'auto';

    // Show typing indicator
    const typingIndicator = addTypingIndicator();

    // Disable input
    sendButton.disabled = true;
    chatInput.disabled = true;

    try {
        // Call Invoice Agent API through nginx proxy
        const response = await fetch('/api/agent/ask', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ 
                question: message,
                session_id: sessionId
            })
        });

        const data = await response.json();
        typingIndicator.remove();

        if (response.ok && data.answer) {
            // Show answer from agent
            addMessage('assistant', data.answer);
            
            // Log SQL if present (for debugging)
            if (data.sql_executed) {
                console.log('SQL ejecutado:', data.sql_executed);
            }
        } else if (data.error_message) {
            addMessage('assistant', `⚠️ ${data.error_message}`);
        } else {
            addMessage('assistant', 'Lo siento, hubo un error al procesar tu pregunta.');
        }
    } catch (error) {
        typingIndicator.remove();
        console.error('Chat error:', error);
        addMessage('assistant', '❌ Error de conexión con el servicio de consultas. Por favor, intenta de nuevo.');
    } finally {
        sendButton.disabled = false;
        chatInput.disabled = false;
        chatInput.focus();
    }
}

function addMessage(type, content) {
    const messageDiv = document.createElement('div');
    messageDiv.className = `message ${type}`;

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = type === 'user' ? 'TU' : '🤖';

    const contentDiv = document.createElement('div');
    contentDiv.className = 'message-content';
    contentDiv.textContent = content;

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(contentDiv);
    chatMessages.appendChild(messageDiv);

    chatMessages.scrollTop = chatMessages.scrollHeight;
}

function addTypingIndicator() {
    const messageDiv = document.createElement('div');
    messageDiv.className = 'message assistant';

    const avatar = document.createElement('div');
    avatar.className = 'message-avatar';
    avatar.textContent = '🤖';

    const typingDiv = document.createElement('div');
    typingDiv.className = 'typing-indicator active';
    typingDiv.innerHTML = '<div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div>';

    messageDiv.appendChild(avatar);
    messageDiv.appendChild(typingDiv);
    chatMessages.appendChild(messageDiv);
    chatMessages.scrollTop = chatMessages.scrollHeight;

    return messageDiv;
}
