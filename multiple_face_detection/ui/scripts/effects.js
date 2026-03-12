const cursor = document.getElementById('cursor');
let cx = 0, cy = 0, tx = 0, ty = 0;
function loop() {
  cx += (tx - cx) * 0.2;
  cy += (ty - cy) * 0.2;
  cursor.style.transform = `translate(${cx - 9}px, ${cy - 9}px)`;
  requestAnimationFrame(loop);
}
document.addEventListener('mousemove', (e) => { tx = e.clientX; ty = e.clientY; });
loop();
function activatePageTransition() {
  const el = document.getElementById('pageContent');
  el.classList.remove('active');
  requestAnimationFrame(() => { el.classList.add('active'); });
}
window.addEventListener('hashchange', activatePageTransition);
window.addEventListener('DOMContentLoaded', activatePageTransition);
