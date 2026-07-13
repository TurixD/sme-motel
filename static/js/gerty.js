/* gerty.js — GertyController: estados, parpadeo, polling (Fase 6)
   Convención: no strings en onclick inline; todo via addEventListener */

(function () {
    var svg = document.querySelector('.gerty-svg');
    if (!svg) return;

    var currentState        = svg.dataset.state || 'default';
    var isHappy             = false;
    var isProcessing        = false;
    var easterActive        = false;
    var blinkTimer          = null;
    var pollTimer           = null;
    var happyTimer          = null;
    var easterTimer         = null;
    var processingStartTime = 0;
    var processingTimer     = null;

    var ROUTE_LABELS = {
        '/':             'DASHBOARD',
        '/ingresos':     'INGRESOS',
        '/gastos':       'GASTOS',
        '/inventario':   'INVENTARIO',
        '/empleados':    'EMPLEADOS',
        '/fondos':       'FONDOS',
        '/reportes':     'REPORTES',
        '/asistente':    'ASISTENTE',
        '/configuracion':'CONFIGURACION',
    };

    /* ── Cambio de estado ── */
    function setState(s) {
        currentState = s;
        svg.dataset.state = s;
        manageBlink();
    }

    function poll() {
        fetch('/api/gerty/estado')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (isHappy || isProcessing || easterActive) return;
                setState(data.estado);
            })
            .catch(function () { /* red inestable: se queda en estado actual */ });
    }

    /* ── Parpadeo aleatorio (8-15 s) ── */
    function manageBlink() {
        if (blinkTimer) { clearTimeout(blinkTimer); blinkTimer = null; }
        if (currentState === 'dormido' || currentState === 'procesando' ||
            currentState === 'enojado' || currentState === 'chiveado') return;
        scheduleBlink();
    }

    function scheduleBlink() {
        var delay = 8000 + Math.random() * 7000;
        blinkTimer = setTimeout(doBlink, delay);
    }

    function doBlink() {
        svg.classList.add('is-blinking');
        setTimeout(function () {
            svg.classList.remove('is-blinking');
            scheduleBlink();
        }, 150);
    }

    /* ── Etiqueta de contexto (nombre de ruta al cargar) ── */
    function showContextLabel(text) {
        var label = document.getElementById('gerty-ctx-label');
        if (!label) return;
        label.textContent = text;
        label.style.opacity = '1';
        setTimeout(function () {
            label.style.opacity = '0';
        }, 1500);
    }

    /* ── Parpadeo: API pública ── */
    function startBlinking() {
        if (blinkTimer) clearTimeout(blinkTimer);
        scheduleBlink();
    }

    function stopBlinking() {
        if (blinkTimer) { clearTimeout(blinkTimer); blinkTimer = null; }
    }

    /* ── Reacción feliz (2s temporales, restaura estado previo directamente) ── */
    function happyReaction() {
        var prevState = (currentState === 'happy') ? 'default' : currentState;
        isHappy = true;
        if (happyTimer) clearTimeout(happyTimer);
        setState('happy');
        happyTimer = setTimeout(function () {
            isHappy = false;
            setState(prevState);
        }, 2000);
    }

    /* ── Estado procesando con mínimo 300ms de visibilidad ── */
    function setProcessing(active) {
        if (active) {
            if (processingTimer) { clearTimeout(processingTimer); processingTimer = null; }
            isProcessing = true;
            processingStartTime = Date.now();
            setState('procesando');
        } else {
            var elapsed   = Date.now() - processingStartTime;
            var remaining = Math.max(0, 300 - elapsed);
            processingTimer = setTimeout(function () {
                processingTimer = null;
                isProcessing = false;
                poll();
            }, remaining);
        }
    }

    /* ── Easter egg: enojado → chiveado (desde dormido) o chiveado directo (despierto) ── */
    function activarEnojado() {
        easterActive = true;
        setState('enojado');
        var wrap = svg.closest('.gerty-widget') || svg.closest('.gerty-avatar') || svg;
        wrap.classList.add('gerty-enojado-anim');
        setTimeout(function () { wrap.classList.remove('gerty-enojado-anim'); }, 250);
        if (easterTimer) clearTimeout(easterTimer);
        easterTimer = setTimeout(function () {
            easterActive = false;
            setState('dormido');
        }, 3000);
    }

    function activarChiveado() {
        clearTimeout(easterTimer);
        setState('chiveado');
        easterTimer = setTimeout(function () {
            easterActive = false;
            setState('dormido');
        }, 2000);
    }

    function activarChiveadoDirecto() {
        var estadoAnterior = currentState;
        easterActive = true;
        if (easterTimer) clearTimeout(easterTimer);
        setState('chiveado');
        easterTimer = setTimeout(function () {
            easterActive = false;
            setState(estadoAnterior);
        }, 2000);
    }

    /* ── Click: redirigir a /asistente (admin) o chiveado breve (empleado), easter egg (doble) ── */
    var singleTimer = null;
    var justDragged = false;   // true justo después de arrastrar, para no navegar por error
    svg.addEventListener('dblclick', function (e) {
        e.preventDefault();
        clearTimeout(singleTimer);
        if (currentState === 'dormido') {
            activarEnojado();
        } else {
            activarChiveadoDirecto();
        }
    });
    svg.addEventListener('click', function () {
        if (justDragged) return;   // fue un arrastre, no un tap: ignora
        clearTimeout(singleTimer);
        singleTimer = setTimeout(function () {
            if (easterActive) {
                if (currentState === 'enojado') activarChiveado();
                return;
            }
            var esAdmin = (window.MODO_ACTUAL || '').indexOf('admin_') === 0;
            if (!esAdmin) {
                activarChiveadoDirecto();
                return;
            }
            if (!window.location.pathname.startsWith('/asistente')) {
                window.location.href = '/asistente';
            }
        }, 220);
    });

    /* ── Arrastrar y aventar para esconder: sale por el borde, vuelve en ~1 min ── */
    var widget = svg.closest('.gerty-widget');
    if (widget && window.PointerEvent) {
        var HIDE_MS        = 60000;   // 1 minuto escondido
        var MOVE_THRESHOLD = 8;       // px para distinguir arrastre de tap
        var dragging = false, moved = false, pointerId = null;
        var startX = 0, startY = 0, curX = 0, curY = 0;
        var lastX = 0, lastY = 0, lastT = 0, velX = 0, velY = 0;
        var hideTimer = null;

        function setTranslate(x, y) {
            widget.style.transform = 'translate(' + x + 'px,' + y + 'px)';
        }

        function onDown(e) {
            if (widget.classList.contains('gerty-hidden')) return;
            dragging = true; moved = false; pointerId = e.pointerId;
            startX = lastX = e.clientX; startY = lastY = e.clientY;
            curX = curY = velX = velY = 0; lastT = e.timeStamp;
            widget.style.animation = 'none';
            widget.style.transition = 'none';
            try { widget.setPointerCapture(pointerId); } catch (_) {}
        }

        function onMove(e) {
            if (!dragging || e.pointerId !== pointerId) return;
            var dx = e.clientX - startX, dy = e.clientY - startY;
            if (!moved && (Math.abs(dx) > MOVE_THRESHOLD || Math.abs(dy) > MOVE_THRESHOLD)) {
                moved = true;
                widget.classList.add('gerty-dragging');
            }
            if (!moved) return;
            curX = dx; curY = dy;
            setTranslate(dx, dy);
            var dt = e.timeStamp - lastT;
            if (dt > 0) {
                velX = (e.clientX - lastX) / dt;   // px/ms
                velY = (e.clientY - lastY) / dt;
            }
            lastX = e.clientX; lastY = e.clientY; lastT = e.timeStamp;
            e.preventDefault();
        }

        function onUp(e) {
            if (!dragging || e.pointerId !== pointerId) return;
            dragging = false;
            widget.classList.remove('gerty-dragging');
            try { widget.releasePointerCapture(pointerId); } catch (_) {}

            var speed = Math.hypot(velX, velY);          // px/ms
            var dist  = Math.hypot(curX, curY);
            if (moved && (speed > 0.6 || dist > 110)) {
                dismiss();
            } else {
                widget.style.transition = 'transform 260ms cubic-bezier(.2,.8,.3,1)';
                setTranslate(0, 0);
                setTimeout(clearInline, 300);
            }
            if (moved) { justDragged = true; setTimeout(function () { justDragged = false; }, 60); }
        }

        function clearInline() {
            widget.style.transition = 'none';
            widget.style.transform  = '';
            widget.style.animation  = '';   // reanuda el flotar
        }

        function dismiss() {
            var dirX = velX, dirY = velY;
            if (Math.hypot(dirX, dirY) < 0.05) { dirX = curX; dirY = curY; }
            var mag   = Math.hypot(dirX, dirY) || 1;
            var reach = Math.max(window.innerWidth, window.innerHeight) * 1.5;
            setTranslate(curX + (dirX / mag) * reach, curY + (dirY / mag) * reach);
            widget.style.transition = 'transform 320ms cubic-bezier(.5,0,.9,.4)';
            widget.classList.add('gerty-hidden');
            if (hideTimer) clearTimeout(hideTimer);
            hideTimer = setTimeout(reaparecer, HIDE_MS);
        }

        function reaparecer() {
            widget.style.transition = 'none';
            widget.style.animation  = 'none';
            setTranslate(180, 0);                 // fuera de pantalla, a la derecha
            widget.classList.remove('gerty-hidden');
            void widget.offsetWidth;              // fuerza reflow
            requestAnimationFrame(function () {
                widget.style.transition = 'transform 1200ms cubic-bezier(.2,.85,.25,1)';
                setTranslate(0, 0);               // entra despacito
                setTimeout(clearInline, 1250);
            });
        }

        widget.addEventListener('pointerdown', onDown);
        widget.addEventListener('pointermove', onMove);
        widget.addEventListener('pointerup', onUp);
        widget.addEventListener('pointercancel', onUp);
    }

    /* ── Inicialización ── */
    // Etiqueta de ruta al cargar
    var path = window.location.pathname;
    for (var route in ROUTE_LABELS) {
        if (path === route || (route !== '/' && path.startsWith(route))) {
            showContextLabel(ROUTE_LABELS[route]);
            break;
        }
    }

    setState(currentState);
    poll();
    pollTimer = setInterval(poll, 30000);

    // Limpiar al salir de la página
    window.addEventListener('pagehide', function () {
        clearInterval(pollTimer);
        if (blinkTimer) clearTimeout(blinkTimer);
    });

    /* ── API pública para otros scripts ── */
    window.Gerty = {
        setState:      setState,
        setProcessing: setProcessing,
        happyReaction: happyReaction,
        startBlinking: startBlinking,
        stopBlinking:  stopBlinking,
    };
})();
