import { TabBar } from './components/TabBar.js';
import { DashboardPage } from './pages/dashboard.js';
import { AttendancePage } from './pages/attendance.js';
import { PeoplePage } from './pages/people.js';
// Pruned: only Dashboard and Attendance routes remain

const routes = {
  '/dashboard': {
    title: 'Dashboard',
    subtitle: 'Overview of activity and KPIs',
    tabs: ['Overview', 'My Plan'],
    render: DashboardPage
  },
  '/attendance': {
    title: 'Attendance',
    subtitle: 'Track employee presence and confidence',
    tabs: [],
    render: AttendancePage
  },
  '/registered': {
    title: 'Registered Users',
    subtitle: 'Manage labeled identities',
    tabs: [],
    render: PeoplePage
  },
}

function $(sel) { return document.querySelector(sel); }

function setActiveNav(hash) {
  document.querySelectorAll('.nav-item').forEach(a => {
    const active = a.getAttribute('href') === hash;
    a.classList.toggle('active', active);
  });
}

function renderHeader(route) {
  $('#pageTitle').textContent = route.title;
  $('#pageSubtitle').textContent = route.subtitle;
}

function renderTabs(route) {
  const container = $('#pageTabs');
  container.innerHTML = '';
  if (!route.tabs || route.tabs.length === 0) return;
  const tabBar = TabBar(route.tabs, (tab) => {
    window.currentTab = tab;
    renderContent(route);
  });
  container.appendChild(tabBar);
  window.currentTab = route.tabs[0];
}

function clearContent() {
  $('#pageContent').innerHTML = '';
}

function renderContent(route) {
  clearContent();
  const node = route.render({ tab: window.currentTab });
  $('#pageContent').appendChild(node);
}

function navigate() {
  const hash = window.location.hash || '#/dashboard';
  setActiveNav(hash);
  const path = hash.replace('#', '');
  const route = routes[path] || routes['/dashboard'];
  const actions = document.getElementById('pageActions');
  if (actions) actions.style.display = (path === '/dashboard') ? 'flex' : 'none';
  renderHeader(route);
  renderTabs(route);
  renderContent(route);
}

function initSidebarToggle() {
  const sidebar = document.querySelector('.sidebar');
  $('#sidebarToggle').addEventListener('click', () => {
    sidebar.classList.toggle('open');
  });
}

window.addEventListener('hashchange', navigate);
window.addEventListener('DOMContentLoaded', () => {
  initSidebarToggle();
  navigate();
});
