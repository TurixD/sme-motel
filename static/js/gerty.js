/* gerty.js — GertyController: estados, parpadeo, polling (Fase 6)
   Convención: no strings en onclick inline; todo via addEventListener */

(function () {
    var svg = document.querySelector('.gerty-svg');
    if (!svg) return;

    var currentState        = svg.dataset.state || 'default';
    var isHappy             = false;
    var isProcessing        = false;
    var blinkTimer          = null;
    var pollTimer           = null;
    var happyTimer          = null;
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

    /* ── Polling: calcula el estado real ── */
    function computeState(data) {
        if (isHappy)      return 'happy';
        if (isProcessing) return 'procesando';
        var h = data.contexto.hora_servidor;
        if (h >= 23 || h <= 6) return 'dormido';
        if (data.contexto.fondo_reserva_bajo || data.contexto.fondo_renta_bajo) return 'alerta';
        if (data.contexto.hay_turno_turi) return 'turno_turi';
        return 'default';
    }

    function poll() {
        fetch('/api/gerty/estado')
            .then(function (r) { return r.json(); })
            .then(function (data) {
                if (!isHappy && !isProcessing) {
                    setState(computeState(data));
                }
            })
            .catch(function () { /* red inestable: se queda en estado actual */ });
    }

    /* ── Parpadeo aleatorio (8-15 s) ── */
    function manageBlink() {
        if (blinkTimer) { clearTimeout(blinkTimer); blinkTimer = null; }
        if (currentState === 'dormido' || currentState === 'procesando') return;
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

    /* ── Easter egg (doble click) ── */
    function easterEgg() {
        svg.classList.add('is-easter');
        var wrap = svg.closest('.gerty-widget') || svg.closest('.gerty-avatar');
        if (wrap) wrap.classList.add('gerty-wiggle');
        setTimeout(function () {
            svg.classList.remove('is-easter');
            if (wrap) wrap.classList.remove('gerty-wiggle');
            setState(currentState);
        }, 2000);
    }

    /* ── Click: redirigir a /asistente (simple), easter egg (doble) ── */
    var singleTimer = null;
    svg.addEventListener('dblclick', function (e) {
        e.preventDefault();
        clearTimeout(singleTimer);
        easterEgg();
    });
    svg.addEventListener('click', function () {
        clearTimeout(singleTimer);
        singleTimer = setTimeout(function () {
            if (!window.location.pathname.startsWith('/asistente')) {
                window.location.href = '/asistente';
            }
        }, 220);
    });

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
