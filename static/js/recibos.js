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

    var _blob           = null;
    var _reciboId       = null;
    var _lineaParaCrear = null;
    var _aprendidoPorIdx = {};

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
            var costoStr  = anal.costo_usd ? ' (costo IA: $' + anal.costo_usd.toFixed(6) + ' USD)' : '';
            var confianza = anal.confianza || 'baja';

            prellenarFormulario(anal);

            if (anal.productos && anal.productos.length > 0) {
                mostrarDesglose(anal);
                if (confianza === 'alta') {
                    setEstado("Sam's detectado · " + anal.productos.length + ' productos extraídos' + costoStr + '. Revisa el desglose y confirma.', 'ok');
                } else {
                    setEstado("Sam's detectado · " + anal.productos.length + ' productos extraídos · Confianza ' + confianza.toUpperCase() + costoStr + '. Revisa cuidadosamente.', 'warn');
                }
            } else {
                document.getElementById('desglose-panel').hidden = true;
                if (confianza === 'alta') {
                    setEstado('Datos extraídos · Confianza alta' + costoStr + '. Revisa y guarda.', 'ok');
                } else if (confianza === 'media') {
                    setEstado('Datos extraídos · Confianza MEDIA — revisa cuidadosamente.' + costoStr, 'warn');
                } else {
                    setEstado('BAJA CONFIANZA — la IA no pudo leer bien el recibo. Verifica TODOS los datos manualmente.' + costoStr, 'error');
                }
                document.querySelector('.form-section').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
            }
        })
        .catch(function (err) {
            procesarBtn.disabled = false;
            procesarBtn.textContent = 'Procesar con IA';
            setEstado('Error de conexión: ' + err, 'error');
        });
    }

    // ── Mostrar desglose Sam's ────────────────────────────────
    function mostrarDesglose(anal) {
        var desglosePanel = document.getElementById('desglose-panel');
        var tbody         = document.getElementById('desglose-tbody');
        var badge         = document.getElementById('desglose-badge');
        var diffEl        = document.getElementById('desglose-diff');

        badge.textContent = anal.productos.length + ' productos detectados';

        var sumaDetectada = anal.productos.reduce(function (s, p) { return s + (p.precio_total || 0); }, 0);
        var totalTicket   = anal.monto || 0;
        var diff          = totalTicket - sumaDetectada;

        if (Math.abs(diff) > 0.01) {
            diffEl.hidden = false;
            diffEl.textContent = 'Suma detectada: $' + sumaDetectada.toFixed(2)
                + '  ·  Total ticket: $' + totalTicket.toFixed(2)
                + '  ·  Diferencia: $' + diff.toFixed(2) + ' (impuestos/descuentos — normal)';
        } else {
            diffEl.hidden = true;
        }

        _aprendidoPorIdx = {};
        tbody.innerHTML = '';
        anal.productos.forEach(function (prod, idx) {
            var tr = document.createElement('tr');
            tr.dataset.idx = idx;
            tr.dataset.skuSams = prod.sku_sams || '';

            if (prod.confianza_match === 'aprendido') {
                _aprendidoPorIdx[idx] = {
                    inventarioIdOriginal: prod.match_producto_id,
                    nombreOriginal: prod.match_producto_nombre || '(desconocido)',
                };
            }

            var vecesTitle = prod.veces_confirmado ? 'Aprendido (visto ' + prod.veces_confirmado + ' ' + (prod.veces_confirmado === 1 ? 'vez' : 'veces') + ')' : 'Match aprendido';
            var iconMap = {
                'alta':      '<span class="conf-badge conf-alta" title="Alta confianza">&#10003;</span>',
                'media':     '<span class="conf-badge conf-media" title="Confianza media">&#9888;</span>',
                'baja':      '<span class="conf-badge conf-baja" title="Baja confianza">&#9888;</span>',
                'sin_match': '<span class="conf-badge conf-sin" title="Sin match">&#10005;</span>',
                'aprendido': '<span class="conf-badge conf-aprendido" title="' + escAttr(vecesTitle) + '">&#10024;</span>',
            };
            var icono = iconMap[prod.confianza_match] || iconMap['sin_match'];

            var opciones = '<option value="">— Sin match —</option>';
            if (typeof CATALOGO_INVENTARIO !== 'undefined') {
                CATALOGO_INVENTARIO.forEach(function (c) {
                    var sel = (c.id === prod.match_producto_id) ? ' selected' : '';
                    opciones += '<option value="' + c.id + '"' + sel + '>' + esc(c.nombre) + '</option>';
                });
            }

            var tdMatch = '<td>'
                + '<select class="field-input field-input--sm desglose-match" data-idx="' + idx + '">' + opciones + '</select>';
            if (!prod.match_producto_id) {
                tdMatch += '<button class="btn btn--ghost btn--sm desglose-crear-btn" type="button"'
                    + ' data-idx="' + idx + '" data-texto="' + escAttr(prod.texto_ticket) + '">+ Crear</button>';
            }
            tdMatch += '</td>';

            tr.innerHTML =
                '<td><span class="desglose-ticket-txt">' + esc(prod.texto_ticket) + '</span></td>'
                + '<td><input class="field-input field-input--sm desglose-cant" type="number" min="0" step="any"'
                + ' value="' + (prod.cantidad || 0) + '" data-idx="' + idx + '"></td>'
                + '<td><input class="field-input field-input--sm desglose-unit" type="number" min="0" step="any"'
                + ' value="' + (prod.precio_unitario || 0) + '" data-idx="' + idx + '"></td>'
                + '<td><input class="field-input field-input--sm desglose-total" type="number" min="0" step="any"'
                + ' value="' + (prod.precio_total || 0) + '" data-idx="' + idx + '" readonly></td>'
                + tdMatch
                + '<td>' + icono + '</td>';

            tbody.appendChild(tr);
        });

        // Recalcular precio total al cambiar cant/unit
        tbody.querySelectorAll('.desglose-cant, .desglose-unit').forEach(function (inp) {
            inp.addEventListener('input', function () {
                var i  = this.dataset.idx;
                var tr = tbody.querySelector('tr[data-idx="' + i + '"]');
                var c  = parseFloat(tr.querySelector('.desglose-cant').value) || 0;
                var u  = parseFloat(tr.querySelector('.desglose-unit').value) || 0;
                tr.querySelector('.desglose-total').value = (c * u).toFixed(2);
            });
        });

        // Mostrar/ocultar botón Crear + confirm sobrescritura de aprendido
        tbody.querySelectorAll('.desglose-match').forEach(function (sel) {
            sel.addEventListener('change', function () {
                var i        = parseInt(this.dataset.idx, 10);
                var tr       = tbody.querySelector('tr[data-idx="' + i + '"]');
                var crearBtn = tr.querySelector('.desglose-crear-btn');
                if (crearBtn) crearBtn.hidden = !!this.value;

                var aprendido = _aprendidoPorIdx[i];
                if (aprendido && this.value) {
                    var nuevoId = parseInt(this.value, 10);
                    if (nuevoId !== aprendido.inventarioIdOriginal) {
                        var nuevoNombre = '';
                        if (typeof CATALOGO_INVENTARIO !== 'undefined') {
                            var item = CATALOGO_INVENTARIO.filter(function (c) { return c.id === nuevoId; })[0];
                            nuevoNombre = item ? item.nombre : '(desconocido)';
                        }
                        if (!confirm('Este producto ya estaba matcheado a "' + aprendido.nombreOriginal + '".\n¿Sobrescribir con "' + nuevoNombre + '"?')) {
                            this.value = aprendido.inventarioIdOriginal || '';
                            if (crearBtn) crearBtn.hidden = !!this.value;
                        }
                    }
                }
            });
        });

        // Botones "Crear" por fila
        tbody.querySelectorAll('.desglose-crear-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                _lineaParaCrear = parseInt(this.dataset.idx, 10);
                document.getElementById('nuevo-prod-nombre').value    = this.dataset.texto;
                document.getElementById('nuevo-prod-proveedor').value = "Sam's";
                document.getElementById('nuevo-prod-estado').hidden   = true;
                openModal('modal-nuevo-producto');
            });
        });

        desglosePanel.hidden = false;
        desglosePanel.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }

    // ── Botón "Confirmar y guardar todo" ─────────────────────
    var btnConfirmar = document.getElementById('btn-confirmar-desglose');
    if (btnConfirmar) {
        btnConfirmar.addEventListener('click', function () {
            var tbody    = document.getElementById('desglose-tbody');
            var estEl    = document.getElementById('desglose-estado');

            var productosConfirmados = [];
            tbody.querySelectorAll('tr[data-idx]').forEach(function (tr) {
                var invId     = tr.querySelector('.desglose-match').value;
                if (!invId) return;
                var cantidad   = parseFloat(tr.querySelector('.desglose-cant').value) || 0;
                var precioTot  = parseFloat(tr.querySelector('.desglose-total').value) || 0;
                var texto      = tr.querySelector('.desglose-ticket-txt').textContent;
                var skuSams    = tr.dataset.skuSams || null;
                if (cantidad <= 0) return;
                productosConfirmados.push({
                    inventario_id: parseInt(invId, 10),
                    cantidad:      cantidad,
                    precio_total:  precioTot,
                    texto_ticket:  texto,
                    sku_sams:      skuSams,
                });
            });

            var reciboId = document.getElementById('recibo-id-hidden').value;
            var gatoData = {
                fecha:       document.getElementById('fecha').value,
                categoria:   document.getElementById('categoria').value,
                monto:       parseFloat(document.getElementById('monto').value) || 0,
                descripcion: document.getElementById('descripcion').value.trim(),
                recibo_id:   reciboId ? parseInt(reciboId, 10) : null,
            };

            if (!gatoData.categoria) {
                setDesgloseEstado('Selecciona una categoría en el formulario de abajo.', 'error');
                return;
            }
            if (gatoData.monto <= 0) {
                setDesgloseEstado('El monto debe ser mayor a cero en el formulario de abajo.', 'error');
                return;
            }

            btnConfirmar.disabled = true;
            btnConfirmar.textContent = 'Guardando…';
            setDesgloseEstado('', false);

            fetch('/gastos/registrar_con_desglose', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ gasto: gatoData, productos: productosConfirmados }),
            })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                btnConfirmar.disabled = false;
                btnConfirmar.textContent = 'Confirmar y guardar todo';
                if (!res.ok) {
                    setDesgloseEstado(res.error || 'Error al guardar.', 'error');
                    return;
                }
                var msg = "Gasto Sam's registrado con " + res.movimientos_creados + ' entrada(s) en inventario';
                if (typeof toast !== 'undefined') toast(msg, 'success');
                setTimeout(function () { location.reload(); }, 900);
            })
            .catch(function (err) {
                btnConfirmar.disabled = false;
                btnConfirmar.textContent = 'Confirmar y guardar todo';
                setDesgloseEstado('Error de conexión: ' + err, 'error');
            });
        });
    }

    // ── Botón "Registrar como gasto normal" ──────────────────
    var btnGastoNormal = document.getElementById('btn-gasto-normal');
    if (btnGastoNormal) {
        btnGastoNormal.addEventListener('click', function () {
            document.getElementById('desglose-panel').hidden = true;
            document.querySelector('.form-section').scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        });
    }

    // ── Modal: crear nuevo producto ───────────────────────────
    var btnCrearProd = document.getElementById('btn-crear-producto');
    if (btnCrearProd) {
        btnCrearProd.addEventListener('click', function () {
            var nombre    = document.getElementById('nuevo-prod-nombre').value.trim();
            var proveedor = document.getElementById('nuevo-prod-proveedor').value.trim();
            var estEl     = document.getElementById('nuevo-prod-estado');

            if (!nombre) {
                estEl.hidden    = false;
                estEl.textContent = 'El nombre es obligatorio.';
                estEl.className = 'recibo-estado recibo-estado--error';
                return;
            }

            btnCrearProd.disabled    = true;
            btnCrearProd.textContent = 'Creando…';

            fetch('/inventario/productos', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ nombre: nombre, proveedor_default: proveedor }),
            })
            .then(function (r) { return r.json(); })
            .then(function (res) {
                btnCrearProd.disabled    = false;
                btnCrearProd.textContent = 'Crear producto';

                if (!res.ok) {
                    estEl.hidden    = false;
                    estEl.textContent = res.error || 'Error al crear el producto.';
                    estEl.className = 'recibo-estado recibo-estado--error';
                    return;
                }

                if (typeof CATALOGO_INVENTARIO !== 'undefined') {
                    CATALOGO_INVENTARIO.push({ id: res.id, nombre: nombre });
                }

                if (_lineaParaCrear !== null) {
                    var tbody = document.getElementById('desglose-tbody');
                    var tr    = tbody.querySelector('tr[data-idx="' + _lineaParaCrear + '"]');
                    if (tr) {
                        var sel = tr.querySelector('.desglose-match');
                        var opt = document.createElement('option');
                        opt.value    = res.id;
                        opt.textContent = nombre;
                        opt.selected = true;
                        sel.appendChild(opt);
                        var crearBtn = tr.querySelector('.desglose-crear-btn');
                        if (crearBtn) crearBtn.hidden = true;
                    }
                }

                closeModal('modal-nuevo-producto');
                _lineaParaCrear = null;
            })
            .catch(function (err) {
                btnCrearProd.disabled    = false;
                btnCrearProd.textContent = 'Crear producto';
                estEl.hidden    = false;
                estEl.textContent = 'Error de conexión: ' + err;
                estEl.className = 'recibo-estado recibo-estado--error';
            });
        });
    }

    var btnCancelarNuevoProd = document.getElementById('btn-cancelar-nuevo-prod');
    if (btnCancelarNuevoProd) {
        btnCancelarNuevoProd.addEventListener('click', function () {
            closeModal('modal-nuevo-producto');
            _lineaParaCrear = null;
        });
    }

    // ── Pre-llenar formulario de gasto ────────────────────────
    function prellenarFormulario(anal) {
        if (anal.fecha)    document.getElementById('fecha').value       = anal.fecha;
        if (anal.monto)    document.getElementById('monto').value       = anal.monto;
        if (anal.concepto) document.getElementById('descripcion').value = anal.concepto;
        if (anal.categoria_sugerida) {
            var sel = document.getElementById('categoria');
            if (sel) sel.value = anal.categoria_sugerida;
        }
    }

    // ── Utilidades ────────────────────────────────────────────
    function esc(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function escAttr(s) {
        return String(s || '').replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    function setEstado(msg, tipo) {
        if (!msg) { estadoEl.hidden = true; return; }
        estadoEl.hidden = false;
        estadoEl.textContent = msg;
        var sufijo = tipo === 'warn' ? '--warn' : tipo === 'error' ? '--error' : '--ok';
        estadoEl.className = 'recibo-estado recibo-estado' + sufijo;
    }

    function setDesgloseEstado(msg, tipo) {
        var el = document.getElementById('desglose-estado');
        if (!el) return;
        if (!msg) { el.hidden = true; return; }
        el.hidden = false;
        el.textContent = msg;
        var sufijo = tipo === 'warn' ? '--warn' : tipo === 'error' ? '--error' : '--ok';
        el.className = 'recibo-estado recibo-estado' + sufijo;
    }

    function resetEstado() {
        setEstado('', false);
    }

    function resetTodo() {
        _blob = null;
        _reciboId = null;
        _aprendidoPorIdx = {};
        fileInput.value = '';
        if (idHidden) idHidden.value = '';
        prevImg.src = '';
        prevWrap.hidden = true;
        dropzone.hidden = false;
        procesarBtn.hidden = true;
        procesarBtn.disabled = false;
        procesarBtn.textContent = 'Procesar con IA';
        resetEstado();
        document.getElementById('desglose-panel').hidden = true;
    }

}());
