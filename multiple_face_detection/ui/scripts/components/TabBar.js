export function TabBar(labels = [], onChange = () => {}) {
  const container = document.createElement('div');
  container.className = 'tabbar-container';
  labels.forEach((label, i) => {
    const tab = document.createElement('button');
    tab.className = 'tab' + (i === 0 ? ' active' : '');
    tab.type = 'button';
    tab.textContent = label;
    tab.addEventListener('click', () => {
      container.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
      tab.classList.add('active');
      onChange(label);
    });
    tab.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        tab.click();
      }
    });
    container.appendChild(tab);
  });
  return container;
}
