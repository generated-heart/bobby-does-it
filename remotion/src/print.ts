// The print look: every surface is shaded with a screen-space halftone dot screen on paper.
// No image model, no textures: just maths per pixel.
//
// Colours are written straight to the screen as sRGB (the canvas uses `linear flat`, which turns off
// three.js colour management), so the hex values below are exactly what you see.

import * as THREE from 'three';

export const PALETTE = {
  paper: '#F1E7D0',
  ink: '#16120F',
  red: '#D2232A',
  blue: '#2B59C3',
};

/** '#rrggbb' -> THREE.Vector3 in 0..1, with no colour-space conversion. */
export const rgb = (hex: string) => {
  const n = parseInt(hex.slice(1), 16);
  return new THREE.Vector3(((n >> 16) & 255) / 255, ((n >> 8) & 255) / 255, (n & 255) / 255);
};

const VERTEX = /* glsl */ `
varying vec3 vNormal;
varying vec2 vUv;
void main() {
  vNormal = normalize(normalMatrix * normal);
  vUv = uv;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
}
`;

const FRAGMENT = /* glsl */ `
uniform vec3 uBase;      // the colour of the "paper" under this surface
uniform vec3 uInk;       // the dot colour
uniform float uCell;     // dot spacing in pixels
uniform float uTime;     // seconds, for the paper grain
uniform float uShade;    // 1 = shade by the light, 0 = flat (use uDark everywhere)
uniform float uDark;     // extra darkness 0..1
varying vec3 vNormal;
varying vec2 vUv;

float hash(vec2 p) { p = fract(p * vec2(123.34, 456.21)); p += dot(p, p + 45.32); return fract(p.x * p.y); }

// Dots on a 45-degree grid. dark 0 = bare paper, 1 = solid ink.
float halftone(vec2 px, float dark, float cell) {
  dark = clamp(dark, 0.0, 1.0);
  const float c = 0.70710678;
  vec2 p = mat2(c, -c, c, c) * px / cell;
  float d = length(fract(p) - 0.5);
  float r = sqrt(dark) * 0.72;           // dot AREA grows with darkness, so the radius grows as sqrt
  return 1.0 - smoothstep(r - 0.06, r + 0.06, d);
}

void main() {
  vec3 light = normalize(vec3(0.4, 0.8, 0.6));
  float diffuse = max(dot(normalize(vNormal), light), 0.0);
  float dark = mix(uDark, 0.85 - diffuse * 0.75, uShade);   // never solid black: shadows stay dotted
  vec3 col = mix(uBase, uInk, halftone(gl_FragCoord.xy, dark, uCell));
  // paper grain that changes 12 times a second: the slight "boil" of printed stop motion
  float grain = hash(floor(gl_FragCoord.xy / 2.0) + floor(uTime * 12.0) * 7.13);
  gl_FragColor = vec4(col * (0.94 + 0.06 * grain), 1.0);
}
`;

export type PrintOptions = {base: string; ink?: string; cell?: number; shade?: boolean; dark?: number};

export const printMaterial = ({base, ink = PALETTE.ink, cell = 10, shade = true, dark = 0}: PrintOptions) =>
  new THREE.ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    uniforms: {
      uBase: {value: rgb(base)},
      uInk: {value: rgb(ink)},
      uCell: {value: cell},
      uTime: {value: 0},
      uShade: {value: shade ? 1 : 0},
      uDark: {value: dark},
    },
  });
