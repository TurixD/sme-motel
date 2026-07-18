/* asistente.js - Chat del asistente conversacional (Fase 4)
   Convención: nunca strings en onclick inline — todo via data-* y addEventListener */

var SESION_ID = '';
var pendingChanges = {};

document.addEventListener('DOMContentLoaded', function () {
    SESION_ID = document.getElementById('sesion-id').value;

    scrollToBottom();

    document.getElementById('btn-nueva-sesion').addEventListener('click', handleNuevaSesion);
    document.getElementById('btn-enviar').addEventListener('click', handleEnviar);
    document.getElementById('input-mensaje').addEventListener('keydown', handleKeydown);
    document.getElementById('input-mensaje').addEventListener('input', function () { autoResizeTextarea(this); });
    document.getElementById('chat-area').addEventListener('click', handleChatClick);

    // Sugerencias del estado vacío
    document.querySelectorAll('.asistente__vacio-sug').forEach(function (btn) {
        btn.addEventListener('click', function () {
            var texto = btn.textContent.trim();
            document.getElementById('input-mensaje').value = texto;
            document.getElementById('input-mensaje').focus();
        });
    });

    // Pre-cargar change cards del servidor en pendingChanges (para sesiones previas)
    document.querySelectorAll('.cambio-card[data-cambio-id]').forEach(function (card) {
        var id = parseInt(card.dataset.cambioId);
        var tipo = card.dataset.tipo || '';
        if (tipo === 'DELETE') {
            wireDeleteCard(card);
        }
        pendingChanges[id] = true;
    });
});

function handleKeydown(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        handleEnviar();
    }
}

function scrollToBottom() {
    var chatArea = document.getElementById('chat-area');
    chatArea.scrollTop = chatArea.scrollHeight;
}

function handleEnviar() {
    var textarea = document.getElementById('input-mensaje');
    var msg = textarea.value.trim();
    if (!msg) return;
    textarea.value = '';
    autoResizeTextarea(textarea);

    ocultarVacio();
    appendMessage('user', msg);
    showLoading(true);

    if (window.Gerty) window.Gerty.setProcessing(true);

    fetch('/asistente/api/mensaje', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mensaje: msg, sesion_id: SESION_ID })
    })
    .then(function (r) { return r.json(); })
    .then(function (data) {
        if (window.Gerty) setTimeout(function () { window.Gerty.setProcessing(false); }, 500);
        showLoading(false);
        if (data.ok) {
            appendMessage('assistant', data.respuesta);
            if (data.cambios_pendientes && data.cambios_pendientes.length > 0) {
                data.cambios_pendientes.forEach(function (cambio) {
                    appendChangeCard(cambio);
                });
            }
            if (data.descargas && data.descargas.length > 0) {
                data.descargas.forEach(function (d) {
                    appendDownloadCard(d);
                });
            }
        } else if (data.limite_alcanzado) {
            showLimitAlert(data.error);
        } else {
            appendMessage('assistant', 'Error: ' + (data.error || 'Error desconocido.'));
        }
        scrollToBottom();
    })
    .catch(function () {
        if (window.Gerty) setTimeout(function () { window.Gerty.setProcessing(false); }, 500);
        showLoading(false);
        appendMessage('assistant', 'Error de conexión. Verifica que el servidor esté activo.');
        scrollToBottom();
    });
}

function appendMessage(rol, contenido) {
    var chatArea = document.getElementById('chat-area');
    var loading = document.getElementById('msg-loading');

    var div = document.createElement('div');
    div.className = 'msg msg--' + rol;

    var burbuja = document.createElement('div');
    burbuja.className = 'msg__burbuja';
    burbuja.textContent = contenido;

    div.appendChild(burbuja);
    chatArea.insertBefore(div, loading);
    scrollToBottom();
}

function appendDownloadCard(d) {
    var chatArea = document.getElementById('chat-area');
    var loading = document.getElementById('msg-loading');

    var card = document.createElement('div');
    card.className = 'descarga-card';

    var info = document.createElement('div');
    info.className = 'descarga-card__info';
    var titulo = document.createElement('div');
    titulo.className = 'descarga-card__titulo';
    titulo.textContent = '📄 ' + (d.titulo || 'Documento');
    var detalle = document.createElement('div');
    detalle.className = 'descarga-card__detalle';
    detalle.textContent = d.detalle || '';
    info.appendChild(titulo);
    info.appendChild(detalle);

    var link = document.createElement('a');
    link.className = 'btn btn--fund descarga-card__btn';
    link.href = d.url;
    link.textContent = 'Descargar PDF';
    link.setAttribute('download', d.filename || '');

    card.appendChild(info);
    card.appendChild(link);
    chatArea.insertBefore(card, loading);
    scrollToBottom();
}

function appendChangeCard(cambio) {
    pendingChanges[cambio.id] = true;
    var chatArea = document.getElementById('chat-area');
    var loading = document.getElementById('msg-loading');

    var esDanger = cambio.tipo === 'DELETE';

    var card = document.createElement('div');
    card.className = 'cambio-card' + (esDanger ? ' cambio-card--danger' : '');
    card.id = 'cambio-' + cambio.id;
    card.dataset.cambioId = cambio.id;
    card.dataset.tipo = cambio.tipo;

    var esTurnos = cambio.kind && cambio.kind !== 'sql';

    var tipoEl = document.createElement('div');
    tipoEl.className = 'cambio-card__tipo';
    tipoEl.textContent = esTurnos ? 'Plan de turnos' : ('Cambio propuesto (' + cambio.tipo + ')');

    var descEl = document.createElement('div');
    descEl.className = 'cambio-card__desc';
    descEl.textContent = cambio.descripcion_humana;

    var details = document.createElement('details');
    details.className = 'cambio-card__sql-wrap';
    var summary = document.createElement('summary');
    summary.textContent = esTurnos ? 'Ver detalle' : 'Ver SQL';
    var pre = document.createElement('pre');
    pre.className = 'cambio-card__sql';
    pre.textContent = cambio.sql;
    details.appendChild(summary);
    details.appendChild(pre);

    var actionsEl = document.createElement('div');
    actionsEl.className = 'cambio-card__actions';

    var btnConfirmar = document.createElement('button');
    btnConfirmar.className = (esDanger ? 'btn btn--expense' : 'btn btn--fund') + ' btn-confirmar-cambio';
    btnConfirmar.dataset.cambioId = cambio.id;
    btnConfirmar.textContent = 'Confirmar';
    if (esDanger) btnConfirmar.disabled = true;

    var btnCancelar = document.createElement('button');
    btnCancelar.className = 'btn btn--ghost btn-cancelar-cambio';
    btnCancelar.dataset.cambioId = cambio.id;
    btnCancelar.textContent = 'Cancelar';

    actionsEl.appendChild(btnConfirmar);
    actionsEl.appendChild(btnCancelar);

    card.appendChild(tipoEl);
    card.appendChild(descEl);
    card.appendChild(details);

    if (esDanger) {
        var confirmInputWrap = document.createElement('div');
        confirmInputWrap.className = 'cambio-card__confirm-input';
        var confirmInput = document.createElement('input');
        confirmInput.type = 'text';
        confirmInput.className = 'cambio-confirm-text';
        confirmInput.placeholder = 'Escribe CONFIRMAR para habilitar';
        confirmInputWrap.appendChild(confirmInput);
        card.appendChild(confirmInputWrap);
    }

    card.appendChild(actionsEl);
    if (esDanger) wireDeleteCard(card);
    chatArea.insertBefore(card, loading);
    scrollToBottom();
}

function wireDeleteCard(card) {
    var input = card.querySelector('.cambio-confirm-text');
    var btnConfirmar = card.querySelector('.btn-confirmar-cambio');
    if (!input || !btnConfirmar) return;
    input.addEventListener('input', function () {
        btnConfirmar.disabled = (input.value.trim().toUpperCase() !== 'CONFIRMAR');
    });
}

function handleChatClick(e) {
    var btnConfirmar = e.target.closest('.btn-confirmar-cambio');
    if (btnConfirmar) {
        confirmarCambio(parseInt(btnConfirmar.dataset.cambioId));
        return;
    }
    var btnCancelar = e.target.closest('.btn-cancelar-cambio');
    if (btnCancelar) {
        cancelarCambio(parseInt(btnCancelar.dataset.cambioId));
    }
}

function confirmarCambio(id) {
    var card = document.getElementById('cambio-' + id);
    if (!card) return;
    var btnConfirmar = card.querySelector('.btn-confirmar-cambio');
    var btnCancelar = card.querySelector('.btn-cancelar-cambio');
    btnConfirmar.disabled = true;
    if (btnCancelar) btnCancelar.disabled = true;
    btnConfirmar.textContent = 'Ejecutando...';

    fetch('/asistente/api/ejecutar_cambio/' + id, { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
        if (data.ok) {
            card.classList.add('cambio-card--ejecutado');
            var actionsEl = card.querySelector('.cambio-card__actions');
            actionsEl.innerHTML = '';
            var status = document.createElement('span');
            status.className = 'cambio-card__status';
            status.textContent = 'Ejecutado';
            actionsEl.appendChild(status);
            appendMessage('assistant', data.mensaje);
            scrollToBottom();
        } else {
            btnConfirmar.disabled = false;
            if (btnCancelar) btnCancelar.disabled = false;
            btnConfirmar.textContent = 'Confirmar';
            alert('Error: ' + (data.error || 'Error desconocido'));
        }
    })
    .catch(function () {
        btnConfirmar.disabled = false;
        if (btnCancelar) btnCancelar.disabled = false;
        btnConfirmar.textContent = 'Confirmar';
    });
}

function cancelarCambio(id) {
    var card = document.getElementById('cambio-' + id);
    if (!card) return;

    fetch('/asistente/api/cancelar_cambio/' + id, { method: 'POST' })
    .then(function (r) { return r.json(); })
    .then(function (data) {
        if (data.ok) {
            card.classList.add('cambio-card--cancelado');
            var actionsEl = card.querySelector('.cambio-card__actions');
            actionsEl.innerHTML = '';
            var status = document.createElement('span');
            status.className = 'cambio-card__status cambio-card__status--cancelado';
            status.textContent = 'Cancelado';
            actionsEl.appendChild(status);
            appendMessage('assistant', data.mensaje);
            scrollToBottom();
        }
    });
}

function handleNuevaSesion() {
    fetch('/asistente/api/nueva_sesion')
    .then(function (r) { return r.json(); })
    .then(function (data) {
        SESION_ID = data.sesion_id;
        pendingChanges = {};

        var chatArea = document.getElementById('chat-area');
        var loading = document.getElementById('msg-loading');
        chatArea.innerHTML = '';
        chatArea.appendChild(loading);

        mostrarVacio();
        document.getElementById('sesion-label').textContent = 'Nueva sesión';
    });
}

function showLoading(visible) {
    document.getElementById('msg-loading').style.display = visible ? 'flex' : 'none';
    document.getElementById('btn-enviar').disabled = visible;
    document.getElementById('input-mensaje').disabled = visible;
    if (visible) scrollToBottom();
}

function showLimitAlert(msg) {
    var el = document.getElementById('limit-alert');
    if (msg) el.textContent = msg;
    el.style.display = 'block';
    document.getElementById('input-mensaje').disabled = true;
    document.getElementById('btn-enviar').disabled = true;
}

function ocultarVacio() {
    var vacio = document.getElementById('chat-vacio');
    if (vacio) vacio.style.display = 'none';
}

function mostrarVacio() {
    var vacio = document.getElementById('chat-vacio');
    if (vacio) vacio.style.display = 'flex';
}

function autoResizeTextarea(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 5 * 24) + 'px';
}
