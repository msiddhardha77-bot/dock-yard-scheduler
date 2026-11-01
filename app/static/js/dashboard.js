document.addEventListener('DOMContentLoaded', () => {
	document.querySelectorAll('table').forEach(table => table.classList.add('align-middle'));

	const sidebar = document.getElementById('app-sidebar');
	const toggle = document.getElementById('menu-toggle');
	const scrim = document.getElementById('sidebar-scrim');
	const closeMenu = () => {
		sidebar?.classList.remove('is-open');
		scrim?.classList.remove('is-visible');
		toggle?.setAttribute('aria-expanded', 'false');
	};
	toggle?.addEventListener('click', () => {
		const open = sidebar.classList.toggle('is-open');
		scrim?.classList.toggle('is-visible', open);
		toggle.setAttribute('aria-expanded', String(open));
	});
	scrim?.addEventListener('click', closeMenu);
	sidebar?.querySelectorAll('a').forEach(link => link.addEventListener('click', closeMenu));

	document.querySelectorAll('form[data-submit-feedback]').forEach(form => {
		form.addEventListener('submit', () => {
			const button = form.querySelector('button[type="submit"], button:not([type])');
			if (!button || button.disabled) return;
			button.dataset.originalLabel = button.innerHTML;
			button.disabled = true;
			button.setAttribute('aria-busy', 'true');
			button.innerHTML = '<span class="spinner-border spinner-border-sm" aria-hidden="true"></span><span>Working…</span>';
		});
	});

	const readChartData = id => {
		const node = document.getElementById(id);
		if (!node) return null;
		try { return JSON.parse(node.textContent); } catch { return null; }
	};
	const colors = ['#159b78', '#d78c32', '#c34f43', '#4b8290', '#66736e', '#97b5a8'];
	const statusData = readChartData('status-chart-data');
	const statusCanvas = document.getElementById('status-chart');
	if (statusData && statusCanvas && window.Chart) {
		new Chart(statusCanvas, {
			type: 'doughnut',
			data: { labels: statusData.labels, datasets: [{ data: statusData.values, backgroundColor: colors, borderWidth: 0, hoverOffset: 5 }] },
			options: { maintainAspectRatio: false, cutout: '68%', plugins: { legend: { position: 'bottom', labels: { usePointStyle: true, boxWidth: 7, padding: 16 } } } }
		});
	}
	const directionData = readChartData('direction-chart-data');
	const directionCanvas = document.getElementById('direction-chart');
	if (directionData && directionCanvas && window.Chart) {
		new Chart(directionCanvas, {
			type: 'bar',
			data: { labels: directionData.labels, datasets: [{ data: directionData.values, backgroundColor: ['#159b78', '#d78c32'], borderRadius: 4, maxBarThickness: 46 }] },
			options: { maintainAspectRatio: false, plugins: { legend: { display: false } }, scales: { y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: '#edf0ed' } }, x: { grid: { display: false } } } }
		});
	}
	const decisionData = readChartData('decision-chart-data');
	const decisionCanvas = document.getElementById('decision-chart');
	if (decisionData && decisionCanvas && window.Chart) {
		new Chart(decisionCanvas, {
			type: 'bar',
			data: { labels: decisionData.labels, datasets: [{ data: decisionData.values, backgroundColor: ['#159b78', '#c34f43'], borderRadius: 4, maxBarThickness: 42 }] },
			options: { maintainAspectRatio: false, indexAxis: 'y', plugins: { legend: { display: false } }, scales: { x: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: '#edf0ed' } }, y: { grid: { display: false } } } }
		});
	}
});
