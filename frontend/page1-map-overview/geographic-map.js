'use strict';

const cityCoordinates = {
  CH: [47.3769, 8.5417],
  DE: [50.1109, 8.6821],
  IE: [53.3498, -6.2603],
};

async function createGeographicMap(container, headquarters, markers, onSelect) {
  const distribution = 'https://unpkg.com/leaflet@1.9.4/dist/';
  const style = document.createElement('link');
  style.rel = 'stylesheet';
  style.href = distribution + 'leaflet.css';
  style.integrity = 'sha256-p4NxAoJBhIIN+hmNHrzRCf9tD/miZyoHS5obTRR9BMY=';
  const script = document.createElement('script');
  script.src = distribution + 'leaflet.js';
  script.integrity = 'sha256-20nQCchB9co0qIjJZRGuk2/Z9VM+kNiyxNV1lvTlZBo=';

  function load(element) {
    return new Promise((resolve, reject) => {
      element.crossOrigin = 'anonymous';
      element.onload = resolve;
      element.onerror = reject;
      document.head.append(element);
    });
  }

  function withinTimeout(promise) {
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = setTimeout(() => reject(new Error('Map request timed out.')), 6500);
    });
    return Promise.race([promise, timeout]).finally(() => clearTimeout(timer));
  }

  await withinTimeout(Promise.all([load(style), load(script)]));
  const leaflet = window.L;
  const map = leaflet.map(container, {
    maxZoom: 16, minZoom: 3, zoomSnap: .25, scrollWheelZoom: false, preferCanvas: true, fadeAnimation: false,
  });
  const basel = leaflet.latLng(47.56, 7.59);
  const destinations = Object.values(cityCoordinates);
  const detailSpace = window.matchMedia('(min-width: 721px)').matches
    ? Math.min(360, container.clientWidth * .41) + 40
    : 38;
  map.fitBounds([basel, ...destinations], {
    paddingTopLeft: [38, 55], paddingBottomRight: [detailSpace, 55], maxZoom: 6,
  });

  const baselPin = document.createElement('div');
  const baselLabel = headquarters.cloneNode(true);
  baselLabel.removeAttribute('id');
  leaflet.DomEvent.disableClickPropagation(baselLabel);
  baselLabel.addEventListener('click', () => onSelect(baselLabel.dataset.location));
  baselPin.append(baselLabel);
  leaflet.marker(basel, {
    icon: leaflet.divIcon({ className: 'basel-pin', html: baselPin, iconSize: [11, 11] }),
    interactive: false,
    keyboard: false,
  }).addTo(map);

  const connections = new Map();
  for (const marker of markers) {
    const key = marker.dataset.location;
    const destination = leaflet.latLng(cityCoordinates[key]);
    const path = leaflet.polyline([basel, destination], { interactive: false }).addTo(map);
    const head = document.createElement('span');
    const arrow = leaflet.marker(basel, {
      icon: leaflet.divIcon({ className: 'map-direction', html: head, iconSize: [14, 14] }),
      interactive: false,
      keyboard: false,
    }).addTo(map);
    const button = marker.cloneNode(true);
    leaflet.DomEvent.disableClickPropagation(button);
    button.addEventListener('click', () => onSelect(key));
    leaflet.marker(destination, {
      icon: leaflet.divIcon({ className: 'geo-marker', html: button, iconSize: [28, 28] }),
      keyboard: false,
    }).addTo(map);
    connections.set(key, { path, arrow, head, button, destination, fraction: 0 });
  }

  let hqFraction = 0;
  const maxDiameter = () => map.getZoom() <= 4.5 ? 23 : 34;
  const bubbleDiameter = fraction => Math.max(10, fraction * maxDiameter());

  function positionConnection({ arrow, head, button, destination, fraction }) {
    const origin = map.latLngToLayerPoint(basel);
    const offset = map.latLngToLayerPoint(destination).subtract(origin);
    const distance = Math.hypot(offset.x, offset.y);
    const diameter = bubbleDiameter(fraction);
    button.style.setProperty('--bubble', `${diameter}px`);

    const startClearance = bubbleDiameter(hqFraction) / 2 + 3;
    const endClearance = diameter / 2 + 3;
    const visibleLength = distance - startClearance - endClearance;
    head.hidden = visibleLength < 4;
    if (head.hidden) return;

    const midpoint = (startClearance + visibleLength / 2) / distance;
    arrow.setLatLng(map.layerPointToLatLng(origin.add(offset.multiplyBy(midpoint))));
    head.style.transform = `rotate(${Math.atan2(offset.y, offset.x)}rad) scale(${Math.min(1, visibleLength / 12)})`;
  }

  function positionArrows() {
    baselLabel.style.setProperty('--bubble', `${bubbleDiameter(hqFraction)}px`);
    for (const connection of connections.values()) positionConnection(connection);
  }
  map.on('zoomend viewreset', positionArrows);
  positionArrows();

  try {
    const tiles = leaflet.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap contributors</a>',
    });
    await withinTimeout(new Promise((resolve, reject) => {
      let loaded = false;
      tiles.on('tileload', () => { loaded = true; });
      tiles.once('load', () => {
        if (loaded) resolve();
        else reject(new Error('Map tiles are unavailable.'));
      });
      tiles.addTo(map);
    }));
  } catch (error) {
    map.remove();
    container.replaceChildren();
    throw error;
  }

  return {
    updateHeadquarters({ selected, fraction, label, amount }) {
      hqFraction = fraction;
      baselLabel.style.setProperty('--bubble', `${bubbleDiameter(hqFraction)}px`);
      baselLabel.querySelector('.hq-value').textContent = amount;
      baselLabel.setAttribute('aria-expanded', String(selected));
      baselLabel.setAttribute('aria-label', label);
      baselLabel.toggleAttribute('data-empty', !fraction);
    },
    update(key, appearance) {
      const connection = connections.get(key);
      const { path, head, button } = connection;
      connection.fraction = appearance.fraction;
      positionConnection(connection);
      button.setAttribute('aria-expanded', String(appearance.selected));
      button.setAttribute('aria-label', appearance.label);
      button.toggleAttribute('data-empty', appearance.empty);
      button.toggleAttribute('data-waste', appearance.waste);
      const colour = appearance.selected ? '#4e6d36' : '#526e7c';
      path.setStyle({ color: colour, opacity: appearance.selected ? 1 : .88, weight: appearance.selected ? 3 : 2, dashArray: appearance.selected ? undefined : '5 5' });
      head.style.color = colour;
    },
  };
}
