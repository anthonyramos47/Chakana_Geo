/**
 * dock.js — panels that are either anchored (docked at their edge of the window,
 * the default) or loose (a floating window: drag it by its title bar, resize it
 * from its corner). A 📌 button in the title bar switches; the choice, position
 * and size are remembered per panel (localStorage).
 *
 *   dockable(rootElement, titleBarElement, 'scene')
 */

const STORE = 'kayviz.panel.';

function load(key) {
  try { return JSON.parse(localStorage.getItem(STORE + key)) ?? {}; } catch (_) { return {}; }
}
function save(key, state) {
  try { localStorage.setItem(STORE + key, JSON.stringify(state)); } catch (_) {}
}

let _top = 1500;     // a loose panel being used comes to the front

/** Put a panel above the others (e.g. when it is opened). */
export function bringToFront(root) { root.style.zIndex = String(++_top); }

/**
 * @param {HTMLElement} root    the panel (its inline style is its anchored layout)
 * @param {HTMLElement} handle  title bar: drag handle, receives the 📌 button
 * @param {string}      key     remembers the mode, position and size
 */
export function dockable(root, handle, key) {
  const anchored = root.style.cssText;       // restored when the panel is pinned again
  const state = { loose: false, ...load(key) };

  const pin = document.createElement('button');
  pin.type = 'button';
  Object.assign(pin.style, {
    marginLeft: 'auto', marginRight: '4px', background: 'none', border: 'none',
    cursor: 'pointer', fontSize: '11px', padding: '0 2px', lineHeight: '1', flex: 'none',
  });
  // inside the title bar but not its click target (which collapses the panel)
  pin.addEventListener('click', e => { e.stopPropagation(); setLoose(!state.loose); });
  pin.addEventListener('pointerdown', e => e.stopPropagation());
  handle.style.display ||= 'flex';
  handle.style.alignItems ||= 'center';
  // one line: a long title wrapped inside the fixed-height bar and lost its first line
  handle.style.whiteSpace = 'nowrap';
  handle.style.overflow = 'hidden';
  // before the panel's own collapse toggle, if it has one
  handle.insertBefore(pin, handle.children.length ? handle.lastElementChild : null);

  function setLoose(loose, place = null) {
    state.loose = loose;
    if (loose) {
      const r = place ?? root.getBoundingClientRect();
      Object.assign(root.style, {
        position: 'fixed', left: `${r.left}px`, top: `${r.top}px`, right: 'auto',
        bottom: 'auto', transform: 'none', maxHeight: '85vh', overflow: 'auto',
        resize: 'both', boxShadow: '0 6px 24px rgba(0,0,0,.45)', borderRadius: '6px',
        zIndex: String(++_top),
      });
      if (state.width)  root.style.width  = `${state.width}px`;
      if (state.height) root.style.height = `${state.height}px`;
      state.left = r.left; state.top = r.top;
    } else {
      const shown = root.style.display;            // anchoring does not show/hide it
      root.style.cssText = anchored;
      root.style.display = shown;
    }
    pin.textContent = loose ? '📍' : '📌';
    pin.title = loose ? 'Loose — click to anchor it back' : 'Anchored — click to make it a floating window';
    pin.setAttribute('aria-label', loose ? 'Anchor panel' : 'Float panel');
    pin.setAttribute('aria-pressed', String(!loose));
    handle.style.cursor = loose ? 'move' : '';
    save(key, state);
    window.__invalidate?.();
  }

  // Drag a loose panel by its title bar; a drag is not a click (no collapse).
  handle.addEventListener('pointerdown', e => {
    if (!state.loose || e.button !== 0) return;
    const r = root.getBoundingClientRect();
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    let moved = false;
    root.style.zIndex = String(++_top);
    const move = ev => {
      if (!moved && Math.hypot(ev.clientX - e.clientX, ev.clientY - e.clientY) < 4) return;
      moved = true;
      const left = Math.min(Math.max(ev.clientX - dx, 0), window.innerWidth - 60);
      const top  = Math.min(Math.max(ev.clientY - dy, 0), window.innerHeight - 30);
      root.style.left = `${left}px`; root.style.top = `${top}px`;
      state.left = left; state.top = top;
    };
    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      if (moved) {
        save(key, state);
        handle.addEventListener('click', ev => { ev.stopPropagation(); ev.preventDefault(); },
                                { capture: true, once: true });
      }
    };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  });

  // remember the size a loose panel is resized to
  new ResizeObserver(() => {
    if (!state.loose) return;
    state.width = root.offsetWidth; state.height = root.offsetHeight;
    save(key, state);
  }).observe(root);

  setLoose(state.loose, state.loose && state.left != null
    ? { left: state.left, top: state.top } : null);
  return { setLoose, get loose() { return state.loose; } };
}
