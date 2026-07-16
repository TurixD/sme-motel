(function () {
    'use strict';

    /* ── Datos desde el template ─────────────────────────────── */
    const CUARTOS   = window.CUARTOS_DATA   || [];
    const ES_ADMIN  = window.ES_ADMIN       || false;

    /* ── Estado ──────────────────────────────────────────────── */
    let rentasActivas = window.RENTAS_ACTIVAS || [];
    let feedItemsMap  = new Map((window.FEED_ITEMS || []).map(i => [i.id, i]));
    let currentCuartoId  = null;
    let currentDuracion  = 6;
    let lastPollTs       = Date.now();
    let pollTimer        = null;

    /* ── Helpers ─────────────────────────────────────────────── */
    function formatPeso(n) {
        return '$' + Number(n || 0).toLocaleString('es-MX', { maximumFractionDigits: 0 });
    }

    function displayModo(modo) {
        if (modo === 'admin_turi')    return 'Turi';
        if (modo === 'admin_gabriel') return 'Gabriel';
        return 'Empleado';
    }

    function escapeHtml(str) {
        return String(str)
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;');
    }

    function cuartoById(id) {
        return CUARTOS.find(c => c.id === id) || null;
    }

    function cuartoPrice(cuartoId, duracion) {
        const c = cuartoById(cuartoId);
        return c ? (c['precio_' + duracion + 'h'] || 0) : 0;
    }

    /* ── Toast ───────────────────────────────────────────────── */
    let toastTimer = null;
    function showToast(msg, tipo) {
        const el = document.getElementById('toast');
        if (!el) return;
        el.textContent  = msg;
        el.className    = 'toast toast--' + (tipo || 'ok');
        el.hidden       = false;
        clearTimeout(toastTimer);
        toastTimer = setTimeout(() => { el.hidden = true; }, 2800);
    }

    /* ── Polling ─────────────────────────────────────────────── */
    function startPolling() {
        if (pollTimer) clearInterval(pollTimer);
        pollTimer = setInterval(pollFeed, 15000);
    }

    function stopPolling() {
        if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    }

    async function pollFeed() {
        try {
            const res  = await fetch('/cuartos/api/actividad_dia');
            const data = await res.json();
            if (!data.ok) return;

            renderFeed(data.items);
            renderContadores(data.contadores);
            lastPollTs    = Date.now();
            rentasActivas = data.items
                .filter(i => i.estado === 'activo')
                .map(i => ({
                    cuarto_id:     i.cuarto_id,
                    hora_registro: i.hora_registro,
                    duracion_horas: i.duracion_horas,
                }));
        } catch (_) { /* red no disponible — silencioso */ }
    }

    /* Page Visibility API — pausa en tab inactiva */
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            pollFeed();
            startPolling();
        } else {
            stopPolling();
        }
    });

    /* ── Contador de rentas (día operativo) ──────────────────── */
    function renderContadores(cont) {
        if (!cont) return;
        var m = document.getElementById('cont-manana');
        var t = document.getElementById('cont-tarde');
        var n = document.getElementById('cont-noche');
        if (m) m.textContent = cont.manana;
        if (t) t.textContent = cont.tarde;
        if (n) n.textContent = cont.noche;
    }

    /* ── Render del feed ─────────────────────────────────────── */
    function renderFeedItem(item) {
        const hora     = item.hora_registro.substring(0, 5);
        const cancelado = item.estado === 'cancelado';
        const precio   = formatPeso(item.precio_cobrado);

        const editBadge = item.editado
            ? `<span class="feed-item__editado" title="Precio original: ${formatPeso(item.precio_default)}">⚠</span>`
            : '';
        const tarjetaBadge = item.es_tarjeta
            ? '<span class="feed-item__tarjeta" title="Pago con tarjeta">💳</span>'
            : item.es_transferencia
            ? '<span class="feed-item__tarjeta" title="Pago por transferencia">🏦</span>'
            : '';
        const cancelBadge = cancelado
            ? '<span class="feed-item__badge-cancelado">Cancelado</span>'
            : '';

        return `<div class="feed-item${cancelado ? ' feed-item--cancelado' : ''} feed-item--clickable" data-renta-id="${item.id}">
            <span class="feed-item__hora">${hora}</span>
            <div class="feed-item__body">
                <span class="feed-item__tipo">Renta</span>
                <span class="feed-item__desc">Cuarto ${item.cuarto_id} · ${escapeHtml(item.nombre_display)} · ${item.duracion_horas}h</span>
                <span class="feed-item__monto">${precio} ${tarjetaBadge} ${editBadge}</span>
                ${cancelBadge}
            </div>
        </div>`;
    }

    function renderFeed(items) {
        const list = document.getElementById('feed-list');
        if (!list) return;

        const prevIds = new Set(feedItemsMap.keys());
        feedItemsMap  = new Map(items.map(i => [i.id, i]));

        if (items.length === 0) {
            list.innerHTML = '<p class="feed-empty">Sin actividad registrada hoy.</p>';
            return;
        }

        list.innerHTML = items.map(renderFeedItem).join('');

        /* Animación solo para ítems realmente nuevos */
        list.querySelectorAll('[data-renta-id]').forEach(function (el) {
            const id = parseInt(el.dataset.rentaId, 10);
            if (!prevIds.has(id)) el.classList.add('feed-item--new');
        });

        attachFeedClickHandlers();
    }

    function attachFeedClickHandlers() {
        document.querySelectorAll('.feed-item--clickable').forEach(function (el) {
            el.addEventListener('click', function () {
                const id = parseInt(el.dataset.rentaId, 10);
                openModalDetalle(id);
            });
        });
    }

    /* ── Detección de solapamiento ───────────────────────────── */
    function checkOverlap(cuartoId) {
        const now = new Date();
        return rentasActivas.find(function (r) {
            if (r.cuarto_id !== cuartoId) return false;
            const parts  = r.hora_registro.split(':');
            const inicio = new Date();
            inicio.setHours(parseInt(parts[0], 10), parseInt(parts[1], 10), parseInt(parts[2] || 0, 10), 0);
            const fin = new Date(inicio.getTime() + r.duracion_horas * 3600 * 1000);
            return fin > now;
        }) || null;
    }

    /* ── Modal: advertencia de solapamiento ─────────────────── */
    function openModalAdvertencia(msg, onContinuar) {
        document.getElementById('advertencia-msg').textContent = msg;
        document.getElementById('modal-advertencia').hidden    = false;

        const btnContinuar = document.getElementById('btn-adv-continuar');
        const btnCancelar  = document.getElementById('btn-adv-cancelar');

        const newContinuar = btnContinuar.cloneNode(true);
        const newCancelar  = btnCancelar.cloneNode(true);
        btnContinuar.replaceWith(newContinuar);
        btnCancelar.replaceWith(newCancelar);

        newContinuar.addEventListener('click', function () {
            document.getElementById('modal-advertencia').hidden = true;
            onContinuar();
        });
        newCancelar.addEventListener('click', function () {
            document.getElementById('modal-advertencia').hidden = true;
        });
    }

    document.getElementById('modal-advertencia').addEventListener('click', function (e) {
        if (e.target === this) this.hidden = true;
    });

    /* ── Modal: registro de renta ────────────────────────────── */
    function openModalRegistro(cuartoId) {
        currentCuartoId = cuartoId;
        currentDuracion = 6;

        const cuarto = cuartoById(cuartoId);
        if (!cuarto) return;

        document.getElementById('modal-reg-title').textContent =
            'Cuarto ' + cuarto.numero + ' — ' + cuarto.nombre_display;

        /* Precios en cada botón */
        document.querySelectorAll('#reg-dur-selector .dur-btn').forEach(function (btn) {
            const dur = parseInt(btn.dataset.dur, 10);
            btn.querySelector('.dur-btn__price').textContent = formatPeso(cuartoPrice(cuartoId, dur));
            btn.classList.toggle('dur-btn--active', dur === 6);
        });

        document.getElementById('reg-precio').value = cuartoPrice(cuartoId, 6);
        document.getElementById('reg-notas').value  = '';
        document.getElementById('reg-metodo').value = 'efectivo';
        document.getElementById('reg-error').hidden = true;
        document.getElementById('modal-registro').hidden = false;
    }

    function closeModalRegistro() {
        document.getElementById('modal-registro').hidden = true;
    }

    /* Selección de duración en modal registro */
    document.querySelectorAll('#reg-dur-selector .dur-btn').forEach(function (btn) {
        btn.addEventListener('click', function () {
            currentDuracion = parseInt(btn.dataset.dur, 10);
            document.querySelectorAll('#reg-dur-selector .dur-btn').forEach(function (b) {
                b.classList.remove('dur-btn--active');
            });
            btn.classList.add('dur-btn--active');
            document.getElementById('reg-precio').value = cuartoPrice(currentCuartoId, currentDuracion);
        });
    });

    document.getElementById('btn-reg-cancelar').addEventListener('click', closeModalRegistro);

    document.getElementById('modal-registro').addEventListener('click', function (e) {
        if (e.target === this) closeModalRegistro();
    });

    document.getElementById('btn-reg-confirmar').addEventListener('click', submitRegistrar);

    async function submitRegistrar() {
        const precio = parseFloat(document.getElementById('reg-precio').value);
        const notas  = document.getElementById('reg-notas').value.trim();
        const metodoPago = document.getElementById('reg-metodo').value;
        const errEl  = document.getElementById('reg-error');

        if (isNaN(precio) || precio < 0) {
            errEl.textContent = 'El precio debe ser un número mayor o igual a 0.';
            errEl.hidden = false;
            return;
        }
        errEl.hidden = true;

        const btn = document.getElementById('btn-reg-confirmar');
        btn.disabled = true;

        try {
            const res  = await fetch('/cuartos/api/registrar', {
                method:  'POST',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({
                    cuarto_id:     currentCuartoId,
                    duracion_horas: currentDuracion,
                    precio_cobrado: precio,
                    notas:          notas || null,
                    metodo_pago:    metodoPago,
                }),
            });
            const data = await res.json();
            if (data.ok) {
                closeModalRegistro();
                showToast('Renta registrada', 'ok');
                await pollFeed();
            } else {
                errEl.textContent = data.error || 'Error al registrar.';
                errEl.hidden = false;
            }
        } catch (_) {
            errEl.textContent = 'Error de conexión.';
            errEl.hidden = false;
        } finally {
            btn.disabled = false;
        }
    }

    /* ── Modal: detalle de renta (admin) ─────────────────────── */
    function openModalDetalle(rentaId) {
        const item = feedItemsMap.get(rentaId);
        if (!item) return;
        renderDetalleDefault(item);
        document.getElementById('modal-detalle').hidden = false;
    }

    function closeModalDetalle() {
        document.getElementById('modal-detalle').hidden = true;
    }

    document.getElementById('modal-detalle').addEventListener('click', function (e) {
        if (e.target === this) closeModalDetalle();
    });

    function renderDetalleDefault(item) {
        const cancelado = item.estado === 'cancelado';
        const content   = document.getElementById('modal-detalle-content');

        const motivo = item.motivo_cancelacion
            ? `<div class="detalle-row detalle-row--full"><span>Motivo</span><span>${escapeHtml(item.motivo_cancelacion)}</span></div>`
            : '';

        const cancelInfo = cancelado ? `
            <div class="detalle-row"><span>Cancelado por</span><span>${displayModo(item.cancelado_por || '')}</span></div>
            <div class="detalle-row"><span>Cancelado a las</span><span>${item.cancelado_at ? item.cancelado_at.substring(11, 16) : '—'}</span></div>
            ${motivo}
        ` : '';

        const editBadge = item.editado
            ? ` <span class="feed-item__editado" title="Original: ${formatPeso(item.precio_default)}">⚠</span>`
            : '';

        const notasRow = item.notas
            ? `<div class="detalle-row detalle-row--full"><span>Notas</span><span>${escapeHtml(item.notas)}</span></div>`
            : '';

        const editadoPorRow = (item.editado && item.editado_por)
            ? `<div class="detalle-row"><span>Editada por</span><span>${displayModo(item.editado_por)}</span></div>`
            : '';

        const actions = !cancelado
            ? `<div class="modal-card__actions">
                   ${ES_ADMIN ? '<button class="btn btn--danger" id="btn-det-cancelar" type="button">Cancelar renta</button>' : ''}
                   <button class="btn btn--${ES_ADMIN ? 'ghost' : 'primary'}" id="btn-det-editar" type="button">Editar</button>
               </div>`
            : `<div class="modal-card__actions">
                   <button class="btn btn--ghost" id="btn-det-cerrar2" type="button">Cerrar</button>
               </div>`;

        content.innerHTML = `
            <div class="modal-header-row">
                <h3 class="modal-card__title">Renta #${item.id}</h3>
                <button class="modal-close-btn" id="btn-det-cerrar" type="button">×</button>
            </div>
            <div class="modal-detalle-info">
                <div class="detalle-row"><span>Cuarto</span><span>Cuarto ${item.cuarto_id} · ${escapeHtml(item.nombre_display)}</span></div>
                <div class="detalle-row"><span>Hora</span><span>${item.hora_registro.substring(0, 5)}</span></div>
                <div class="detalle-row"><span>Duración</span><span>${item.duracion_horas}h</span></div>
                <div class="detalle-row"><span>Precio</span><span>${formatPeso(item.precio_cobrado)}${editBadge}</span></div>
                <div class="detalle-row"><span>Pago</span><span>${item.es_tarjeta ? '💳 Tarjeta' : item.es_transferencia ? '🏦 Transferencia' : 'Efectivo'}</span></div>
                <div class="detalle-row"><span>Registrado por</span><span>${displayModo(item.registrado_por)}</span></div>
                ${notasRow}
                ${editadoPorRow}
                ${cancelInfo}
            </div>
            ${actions}
        `;

        document.getElementById('btn-det-cerrar').addEventListener('click', closeModalDetalle);
        const cerrar2 = document.getElementById('btn-det-cerrar2');
        if (cerrar2) cerrar2.addEventListener('click', closeModalDetalle);

        const btnEditar = document.getElementById('btn-det-editar');
        if (btnEditar) btnEditar.addEventListener('click', function () { openEditMode(item); });

        const btnCancelar = document.getElementById('btn-det-cancelar');
        if (btnCancelar) btnCancelar.addEventListener('click', function () { showCancelarConfirm(item.id); });
    }

    /* ── Modal detalle: confirmar cancelación ────────────────── */
    function showCancelarConfirm(rentaId) {
        const item    = feedItemsMap.get(rentaId);
        const content = document.getElementById('modal-detalle-content');

        content.innerHTML = `
            <h3 class="modal-card__title">Cancelar renta</h3>
            <p class="modal-subtitle">Cuarto ${item.cuarto_id} · ${item.duracion_horas}h · ${formatPeso(item.precio_cobrado)}</p>
            <div class="form-group">
                <label class="form-label" for="cancelar-motivo">Razón (opcional)</label>
                <textarea class="form-input form-textarea" id="cancelar-motivo" rows="2" placeholder="¿Por qué se cancela?"></textarea>
            </div>
            <p class="form-error" id="cancelar-error" hidden></p>
            <div class="modal-card__actions">
                <button class="btn btn--ghost"  id="btn-cancelar-volver"    type="button">Volver</button>
                <button class="btn btn--danger" id="btn-cancelar-confirmar" type="button">Confirmar cancelación</button>
            </div>
        `;

        document.getElementById('btn-cancelar-volver').addEventListener('click', function () {
            renderDetalleDefault(item);
        });

        document.getElementById('btn-cancelar-confirmar').addEventListener('click', async function () {
            const motivo = document.getElementById('cancelar-motivo').value.trim();
            const errEl  = document.getElementById('cancelar-error');
            const btn    = this;
            btn.disabled = true;

            try {
                const res  = await fetch('/cuartos/api/cancelar/' + rentaId, {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({ motivo: motivo || null }),
                });
                const data = await res.json();
                if (data.ok) {
                    closeModalDetalle();
                    showToast('Renta cancelada', 'ok');
                    await pollFeed();
                } else {
                    errEl.textContent = data.error || 'Error al cancelar.';
                    errEl.hidden = false;
                    btn.disabled = false;
                }
            } catch (_) {
                errEl.textContent = 'Error de conexión.';
                errEl.hidden = false;
                btn.disabled = false;
            }
        });
    }

    /* ── Modal detalle: modo edición ─────────────────────────── */
    function openEditMode(item) {
        let editDur   = item.duracion_horas;
        const content = document.getElementById('modal-detalle-content');

        const durSection = ES_ADMIN
            ? `<div class="form-group">
                   <label class="form-label">Duración</label>
                   <div class="dur-selector" id="edit-dur-selector">${
                       [6, 12, 18, 24].map(function (d) {
                           return `<button class="dur-btn${d === editDur ? ' dur-btn--active' : ''}" data-dur="${d}" type="button">${d}h<span class="dur-btn__price">${formatPeso(cuartoPrice(item.cuarto_id, d))}</span></button>`;
                       }).join('')
                   }</div>
               </div>`
            : '';

        content.innerHTML = `
            <h3 class="modal-card__title">Editar renta #${item.id}</h3>
            <p class="modal-subtitle">Cuarto ${item.cuarto_id} · ${escapeHtml(item.nombre_display)}${!ES_ADMIN ? ' · ' + item.duracion_horas + 'h' : ''}</p>
            ${durSection}
            <div class="form-group">
                <label class="form-label" for="edit-precio">Precio cobrado</label>
                <input class="form-input" type="number" id="edit-precio" min="0" step="1" value="${item.precio_cobrado}">
            </div>
            <div class="form-group">
                <label class="form-label" for="edit-metodo">Método de pago</label>
                <select class="form-input" id="edit-metodo">
                    <option value="efectivo" ${!item.es_tarjeta && !item.es_transferencia ? 'selected' : ''}>Efectivo (entra a caja)</option>
                    <option value="tarjeta" ${item.es_tarjeta ? 'selected' : ''}>Tarjeta (banco, 4% comisión)</option>
                    <option value="transferencia" ${item.es_transferencia ? 'selected' : ''}>Transferencia (banco, sin comisión)</option>
                </select>
            </div>
            <div class="form-group">
                <label class="form-label" for="edit-notas">Notas</label>
                <textarea class="form-input form-textarea" id="edit-notas" rows="2">${escapeHtml(item.notas || '')}</textarea>
            </div>
            <p class="form-error" id="edit-error" hidden></p>
            <div class="modal-card__actions">
                <button class="btn btn--ghost"   id="btn-edit-volver"  type="button">Volver</button>
                <button class="btn btn--primary" id="btn-edit-guardar" type="button">Guardar cambios</button>
            </div>
        `;

        if (ES_ADMIN) {
            document.querySelectorAll('#edit-dur-selector .dur-btn').forEach(function (btn) {
                btn.addEventListener('click', function () {
                    editDur = parseInt(btn.dataset.dur, 10);
                    document.querySelectorAll('#edit-dur-selector .dur-btn').forEach(function (b) {
                        b.classList.remove('dur-btn--active');
                    });
                    btn.classList.add('dur-btn--active');
                    document.getElementById('edit-precio').value = cuartoPrice(item.cuarto_id, editDur);
                });
            });
        }

        document.getElementById('btn-edit-volver').addEventListener('click', function () {
            renderDetalleDefault(item);
        });

        document.getElementById('btn-edit-guardar').addEventListener('click', async function () {
            const precio = parseFloat(document.getElementById('edit-precio').value);
            const notas  = document.getElementById('edit-notas').value.trim();
            const errEl  = document.getElementById('edit-error');
            const btn    = this;

            if (isNaN(precio) || precio < 0) {
                errEl.textContent = 'El precio debe ser un número mayor o igual a 0.';
                errEl.hidden = false;
                return;
            }
            errEl.hidden  = true;
            btn.disabled  = true;

            try {
                const res  = await fetch('/cuartos/api/editar/' + item.id, {
                    method:  'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body:    JSON.stringify({
                        duracion_horas: editDur,
                        precio_cobrado: precio,
                        notas:          notas || null,
                        metodo_pago:    document.getElementById('edit-metodo').value,
                    }),
                });
                const data = await res.json();
                if (data.ok) {
                    closeModalDetalle();
                    showToast('Cambios guardados', 'ok');
                    await pollFeed();
                } else {
                    errEl.textContent = data.error || 'Error al guardar.';
                    errEl.hidden = false;
                    btn.disabled = false;
                }
            } catch (_) {
                errEl.textContent = 'Error de conexión.';
                errEl.hidden = false;
                btn.disabled = false;
            }
        });
    }

    /* ── Click en cards del grid ─────────────────────────────── */
    document.querySelectorAll('.cuarto-card').forEach(function (card) {
        card.addEventListener('click', function () {
            const cuartoId = parseInt(card.dataset.cuartoId, 10);
            const overlap  = checkOverlap(cuartoId);

            if (overlap) {
                const h     = overlap.hora_registro.substring(0, 5);
                const fin   = new Date();
                const parts = overlap.hora_registro.split(':');
                fin.setHours(parseInt(parts[0], 10), parseInt(parts[1], 10), 0, 0);
                fin.setTime(fin.getTime() + overlap.duracion_horas * 3600 * 1000);
                const finStr = fin.toLocaleTimeString('es-MX', { hour: '2-digit', minute: '2-digit', hour12: false });

                const msg = 'Cuarto ' + cuartoId + ' tiene una renta de ' + overlap.duracion_horas + 'h '
                    + 'iniciada a las ' + h + ' (termina aprox. a las ' + finStr + '). ¿Continuar?';

                openModalAdvertencia(msg, function () {
                    openModalRegistro(cuartoId);
                });
            } else {
                openModalRegistro(cuartoId);
            }
        });
    });

    /* ── Click en feed inicial (server-rendered) ─────────────── */
    attachFeedClickHandlers();

    /* ── Arrancar polling ────────────────────────────────────── */
    startPolling();

})();
