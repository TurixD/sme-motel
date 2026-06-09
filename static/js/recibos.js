'use strict';

(function () {

    var toggleBtn   = document.getElementById('btn-toggle-recibo');
    var panel       = document.getElementById('recibo-panel');
    var fileInput   = document.getElementById('recibo-file');
    var dropzone    = document.getElementById('recibo-dropzone');
    var prevWrap    = document.getElementById('recibo-preview-wrap');
    var prevImg     = document.getElementById('recibo-preview');
    var cambiarBtn  = document.getElementById('btn-cambiar-foto');
    var procesarBtn = document.getElementById('btn-procesar-ia');
    var estadoEl    = document.getElementById('recibo-estado');
    var idHidden    = document.getElementById('recibo-id-hidden');

    if (!toggleBtn) return;

    var _blob     = null;
    var _reciboId = null;

    // ── Toggle panel ─────────────────────────────────────────
    toggleBtn.addEventListener('click', function () {
        var isOpen = !panel.hidden;
        panel.hidden = isOpen;
        toggleBtn.setAttribute('aria-expanded', String(!isOpen));
        var chevron = toggleBtn.querySelector('.recibo-chevron');
        if (chevron) chevron.style.transform = isOpen ? '' : 'rotate(180deg)';
    });

    // ── Selección de archivo ──────────────────────────────────
    fileInput.addEventListener('change', function () {
        var file = fileInput.files[0];
        if (!file) return;
        resetEstado();
        procesarImagen(file);
    });

    cambiarBtn.addEventListener('click', function () {
        resetTodo();
    });

    procesarBtn.addEventListener('click', function () {
        if (!_blob) return;
        subirYAnalizar();
    });

    // ── Procesar imagen en cliente ────────────────────────────
    function procesarImagen(file) {
        var esHeic = file.type === 'image/heic'
            || file.type === 'image/heif'
            || file.name.toLowerCase().endsWith('.heic')
            || file.name.toLowerCase().endsWith('.heif');

        var esImagen = file.type.startsWith('image/') || esHeic;
        if (!esImagen) {
            setEstado('Solo se aceptan imágenes (JPEG, PNG, HEIC).', 'error');
            return;
        }

        setEstado('Procesando imagen…', false);

        var promise;
        if (esHeic) {
            if (typeof heic2any === 'undefined') {
                setEstado('Formato HEIC no soportado en este navegador. Sube una foto JPEG o PNG.', 'error');
                return;
            }
            promise = heic2any({ blob: file, toType: 'image/jpeg', quality: 0.85 })
                .then(function (converted) {
                    return resizeCompress(Array.isArray(converted) ? converted[0] : converted);
                });
        } else {
            promise = resizeCompress(file);
        }

        promise.then(function (blob) {
            if (blob.size > 2 * 1024 * 1024) {
                setEstado(
                    'La imagen sigue siendo grande después de comprimir ('
                    + Math.round(blob.size / 1024) + ' KB). Intenta con otra foto.',
                    'error'
                );
                return;
            }
            _blob = blob;
            var url = URL.createObjectURL(blob);
            prevImg.src = url;
            dropzone.hidden = true;
            prevWrap.hidden = false;
            procesarBtn.hidden = false;
            setEstado('', false);
        }).catch(function (err) {
            setEstado('Error al procesar la imagen: ' + err, 'error');
        });
    }

    function resizeCompress(blob) {
        return new Promise(function (resolve, reject) {
            var img = new Image();
            var url = URL.createObjectURL(blob);
            img.onload = function () {
                URL.revokeObjectURL(url);
                var MAX = 2048;
                var w = img.naturalWidth;
                var h = img.naturalHeight;
                if (w > MAX || h > MAX) {
                    if (w >= h) { h = Math.round(h * MAX / w); w = MAX; }
                    else        { w = Math.round(w * MAX / h); h = MAX; }
                }
                var canvas = document.createElement('canvas');
                canvas.width = w;
                canvas.height = h;
                canvas.getContext('2d').drawImage(img, 0, 0, w, h);
                canvas.toBlob(function (b) {
                    if (b) resolve(b);
                    else   reject(new Error('No se pudo comprimir la imagen'));
                }, 'image/jpeg', 0.85);
            };
            img.onerror = function () {
                URL.revokeObjectURL(url);
                reject(new Error('No se pudo cargar la imagen'));
            };
            img.src = url;
        });
    }

    // ── Subir y analizar ──────────────────────────────────────
    function subirYAnalizar() {
        procesarBtn.disabled = true;
        procesarBtn.textContent = 'Subiendo…';
        setEstado('Subiendo imagen al servidor…', false);

        var fd = new FormData();
        fd.append('imagen', _blob, 'recibo.jpg');

        fetch('/gastos/recibos/subir', { method: 'POST', body: fd })
        .then(function (r) { return r.json(); })
        .then(function (data) {
            if (!data.ok) {
                setEstado(data.error || 'Error al subir la imagen.', 'error');
                procesarBtn.disabled = false;
                procesarBtn.textContent = 'Procesar con IA';
                return null;
            }
            _reciboId = data.recibo_id;
            if (data.duplicado) {
                setEstado('Foto ya subida anteriormente — reutilizando registro existente.', false);
            }
            procesarBtn.textContent = 'Analizando…';
            setEstado('Analizando con IA…', false);
            return fetch('/gastos/recibos/' + _reciboId + '/analizar', { method: 'POST' })
                .then(function (r) { return r.json(); });
        })
        .then(function (anal) {
            if (!anal) return;
            procesarBtn.disabled = false;
            procesarBtn.textContent = 'Procesar con IA';

            if (!anal.ok) {
                var msg = (anal.error || 'Error al analizar') + '. Puedes llenar el formulario manualmente.';
                setEstado(msg, 'error');
                if (_reciboId) idHidden.value = _reciboId;
                return;
            }

            if (_reciboId) idHidden.value = _reciboId;
            var costoStr   = anal.costo_usd ? ' (costo IA: $' + anal.costo_usd.toFixed(6) + ' USD)' : '';
            var confianza  = anal.confianza || 'baja';

            if (confianza === 'alta') {
                prellenarFormulario(anal);
                setEstado('Datos extraídos · Confianza alta' + costoStr + '. Revisa y guarda.', 'ok');
            } else if (confianza === 'media') {
                prellenarFormulario(anal);
                setEstado('Datos extraídos · Confianza MEDIA — revisa cuidadosamente.' + costoStr, 'warn');
            } else {
                setEstado('BAJA CONFIANZA — la IA no pudo leer bien el recibo. Verifica TODOS los datos manualmente.' + costoStr, 'error');
            }

            document.querySelector('.form-section').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        })
        .catch(function (err) {
            procesarBtn.disabled = false;
            procesarBtn.textContent = 'Procesar con IA';
            setEstado('Error de conexión: ' + err, 'error');
        });
    }

    // ── Pre-llenar formulario de gasto ────────────────────────
    function prellenarFormulario(anal) {
        if (anal.fecha)   document.getElementById('fecha').value       = anal.fecha;
        if (anal.monto)   document.getElementById('monto').value       = anal.monto;
        if (anal.concepto) document.getElementById('descripcion').value = anal.concepto;
        if (anal.categoria_sugerida) {
            var sel = document.getElementById('categoria');
            if (sel) sel.value = anal.categoria_sugerida;
        }
    }

    // ── Utilidades ────────────────────────────────────────────
    function setEstado(msg, tipo) {
        if (!msg) { estadoEl.hidden = true; return; }
        estadoEl.hidden = false;
        estadoEl.textContent = msg;
        var sufijo = tipo === 'warn' ? '--warn' : tipo === 'error' ? '--error' : '--ok';
        estadoEl.className = 'recibo-estado recibo-estado' + sufijo;
    }

    function resetEstado() {
        setEstado('', false);
    }

    function resetTodo() {
        _blob = null;
        _reciboId = null;
        fileInput.value = '';
        if (idHidden) idHidden.value = '';
        prevImg.src = '';
        prevWrap.hidden = true;
        dropzone.hidden = false;
        procesarBtn.hidden = true;
        procesarBtn.disabled = false;
        procesarBtn.textContent = 'Procesar con IA';
        resetEstado();
    }

}());
