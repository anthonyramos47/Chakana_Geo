// Just enough browser globals for the viewer modules to load under node.
const canvas = () => ({
  style: {}, width: 800, height: 600,
  getContext: () => ({
    scale() {}, clearRect() {}, fillRect() {}, fillText() {}, beginPath() {}, arc() {},
    fill() {}, stroke() {}, moveTo() {}, lineTo() {}, measureText: () => ({ width: 5 }),
    roundRect() {}, save() {}, restore() {}, createLinearGradient: () => ({ addColorStop() {} }),
  }),
});
globalThis.window ??= { devicePixelRatio: 1, innerWidth: 800, innerHeight: 600 };
globalThis.document ??= {
  dispatchEvent() {}, addEventListener() {},
  createElement: canvas, body: { appendChild() {} },
};
globalThis.localStorage ??= { getItem: () => null, setItem() {} };
globalThis.CustomEvent ??= class { constructor(type) { this.type = type; } };
