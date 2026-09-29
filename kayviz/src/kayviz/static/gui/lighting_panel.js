/**
 * lighting_panel.js — Scene lighting controls.
 *
 * Embeds a lil-gui instance into a provided container element so it sits
 * inline inside the scene panel rather than floating freely.
 */

import GUI from 'lil-gui';

export class LightingPanel {
  /**
   * @param {HTMLElement}            container  — element to embed the GUI into
   * @param {THREE.AmbientLight}     ambient
   * @param {THREE.DirectionalLight} keyLight
   * @param {THREE.DirectionalLight} fillLight
   */
  constructor(container, ambient, keyLight, fillLight) {
    this.gui = new GUI({ container, title: 'Lighting' });

    // ── Ambient ───────────────────────────────────────────────────────────
    const ambState = { intensity: ambient.intensity };
    const af = this.gui.addFolder('Ambient');
    af.add(ambState, 'intensity', 0, 2, 0.01).name('Intensity')
      .onChange(v => { ambient.intensity = v; });

    // ── Key light ─────────────────────────────────────────────────────────
    const keyState = {
      intensity: keyLight.intensity,
      x: keyLight.position.x,
      y: keyLight.position.y,
      z: keyLight.position.z,
    };
    const kf = this.gui.addFolder('Key Light');
    kf.add(keyState, 'intensity', 0, 3, 0.01).name('Intensity')
      .onChange(v => { keyLight.intensity = v; });
    kf.add(keyState, 'x', -20, 20, 0.1).name('X')
      .onChange(v => { keyLight.position.x = v; });
    kf.add(keyState, 'y', -20, 20, 0.1).name('Y')
      .onChange(v => { keyLight.position.y = v; });
    kf.add(keyState, 'z', -20, 20, 0.1).name('Z')
      .onChange(v => { keyLight.position.z = v; });

    // ── Fill light ────────────────────────────────────────────────────────
    const fillState = {
      intensity: fillLight.intensity,
      x: fillLight.position.x,
      y: fillLight.position.y,
      z: fillLight.position.z,
    };
    const ff = this.gui.addFolder('Fill Light');
    ff.close();
    ff.add(fillState, 'intensity', 0, 3, 0.01).name('Intensity')
      .onChange(v => { fillLight.intensity = v; });
    ff.add(fillState, 'x', -20, 20, 0.1).name('X')
      .onChange(v => { fillLight.position.x = v; });
    ff.add(fillState, 'y', -20, 20, 0.1).name('Y')
      .onChange(v => { fillLight.position.y = v; });
    ff.add(fillState, 'z', -20, 20, 0.1).name('Z')
      .onChange(v => { fillLight.position.z = v; });

    // Strip lil-gui's default absolute positioning so it flows inline
    Object.assign(this.gui.domElement.style, {
      position: 'relative',
      width:    '100%',
    });
  }
}
