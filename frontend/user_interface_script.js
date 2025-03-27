const map = L.map('map').setView([47.3769, 8.5417], 13);


const cartoLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
    attribution: '© OpenStreetMap contributors © CARTO'
  }).addTo(map);

// Nordpfeil hinzufügen
const north = L.control({ position: "topright" });
north.onAdd = function(map) {
  const div = L.DomUtil.create("div", "info legend");
  div.innerHTML = `
    <div style="width: 60px; height: 60px; border: 5px solid black; border-radius: 50%; position: relative; background-color: #fff; text-align: center; font-size: 20px;">
      <div style="position: absolute; top: -20px; left: 50%; transform: translateX(-50%); font-size: 20px; font-weight: bold; color: black;">N</div>
      <div style="position: absolute; top: 5px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 15px solid transparent; border-right: 15px solid transparent; border-bottom: 30px solid black;"></div>
      <div style="position: absolute; top: 25px; left: 50%; transform: translateX(-50%); width: 8px; height: 20px; background-color: black;"></div>
    </div>
  `;
  return div;
};
north.addTo(map);

// Maßstab hinzufügen
L.control.scale().addTo(map);

// LayerControl hinzufügen
const layersControl = L.control.layers({
  "Basiskarte": osmLayer
}, {
  "Car": osmLayer,
  "Bike": osmLayer,
  "Walk": osmLayer
}, { collapsed: false }).addTo(map);

// CRS (Koordinatensystem)-Infofeld hinzufügen
const crsControl = L.control({ position: 'bottomright' });
crsControl.onAdd = function (map) {
  const div = L.DomUtil.create('div', 'leaflet-control-coords');
  div.innerHTML = "<strong>Reference system:</strong> EPSG:3857 (WGS84)";
  div.style.background = "white";
  div.style.padding = "5px";
  div.style.borderRadius = "5px";
  div.style.fontSize = "12px";
  div.style.boxShadow = "0px 0px 5px rgba(0,0,0,0.3)";
  return div;
};
crsControl.addTo(map);
