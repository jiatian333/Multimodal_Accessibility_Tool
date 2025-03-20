function closePopup() {
    document.getElementById("popupOverlay").classList.add("hidden");
}
document.addEventListener("DOMContentLoaded", function() {
    var map = L.map('map-container').setView([47.3769, 8.5417], 13);

    // Basis-Layer hinzufügen
    var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
    
    L.control.scale().addTo(map);

    var north = L.control({position: "topright"});

    north.onAdd = function(map) {
        var div = L.DomUtil.create("div", "info legend");
        div.innerHTML = `
        <div style="width: 60px; height: 60px; border: 5px solid black; border-radius: 50%; position: relative; background-color: #fff; text-align: center; font-size: 20px;">
          <!-- N über dem Kreis -->
          <div style="position: absolute; top: -20px; left: 50%; transform: translateX(-50%); font-size: 20px; font-weight: bold; color: black;">
            N
          </div>
          
          <!-- Pfeil nach oben -->
          <div style="position: absolute; top: 5px; left: 50%; transform: translateX(-50%); width: 0; height: 0; border-left: 15px solid transparent; border-right: 15px solid transparent; border-bottom: 30px solid black;"></div>
          <!-- Schaft des Pfeils -->
          <div style="position: absolute; top: 25px; left: 50%; transform: translateX(-50%); width: 8px; height: 20px; background-color: black;"></div>
        </div>
      `;

        return div;
    }
    
    north.addTo(map);
    
    var getLocationMarker = L.marker([47.3769, 8.5417]).addTo(map);
    var gotoLocationMarker = L.marker([47.3769, 8.5417]).addTo(map);

    var line = L.polyline([gotoLocationMarker.getLatLng(), getLocationMarker.getLatLng()], {color: 'rgba(255, 99, 71, 0.5)'}).addTo(map);
    // Layers-Control mit einem Basis-Layer hinzufügen
    /*const layersControl = new L.control.layers({}, null, {
        collapsed: false,
      });
    
    layersControl.addTo(map);

    layersControl.addOverlay(osmLayer, "Basiskarte");
    layersControl.addOverlay(osmLayer, "Car");
    layersControl.addOverlay(osmLayer, "Bike");
    layersControl.addOverlay(osmLayer, "Walk");*/
    const layersControl = new L.control.layers({
        "Basiskarte": osmLayer  // Basiskarte korrekt hier definieren
    }, {
        "Car": osmLayer,
        "Bike": osmLayer,
        "Walk": osmLayer
    }, { collapsed: false }).addTo(map);

    // HTML-Legende hinzufügen (prüfen, ob das Plugin richtig initialisiert ist)
    /*const htmlLegend = L.control.htmllegend({
        position: "bottomright",
        legends: [{
            name: "Beispiel-Legende",
            elements: [{
                label: "Punkt",
                html: '<div style="width:10px; height:10px; background:red; border-radius:50%;"></div>'
            }]
        }]
    });
    map.addControl(htmlLegend);*/


    document.getElementById('goToLocation').addEventListener('click', function() {
        var lat = parseFloat(document.getElementById('lat').value);
        var lng = parseFloat(document.getElementById('lng').value);
        
        if (!isNaN(lat) && !isNaN(lng)) {
            map.setView([lat, lng], 12);
            gotoLocationMarker.setLatLng([lat, lng]);
            line.setLatLngs([gotoLocationMarker.getLatLng(), getLocationMarker.getLatLng()]);
        } else {
            alert("Bitte gültige Koordinaten eingeben!");
        }
    });
    
    function showPosition(position) {
        var lat = position.coords.latitude; 
        var lng = position.coords.longitude; 
    
        map.setView([lat, lng], 13);
        getLocationMarker.setLatLng([lat, lng]);
        line.setLatLngs([gotoLocationMarker.getLatLng(), getLocationMarker.getLatLng()]);
    }

    document.getElementById("getLocationButton").addEventListener("click", function(){
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(showPosition, showError);
          } else {
            document.getElementById("location").innerHTML = "Geolocation wird von diesem Browser nicht unterstützt.";
          }


    });

    function showError(error) {
        switch(error.code) {
            case error.PERMISSION_DENIED:
                alert("Benutzer hat die Standortfreigabe verweigert.");
                break;
            case error.POSITION_UNAVAILABLE:
                alert("Standortinformationen sind nicht verfügbar.");
                break;
            case error.TIMEOUT:
                alert("Die Standortanforderung ist abgelaufen.");
                break;
            case error.UNKNOWN_ERROR:
                alert("Ein unbekannter Fehler ist aufgetreten.");
                break;
        }
    }
    /*fetch('http://127.0.0.1:5000/data/walk_isochrones_cube.geojson', {
        method: "GET",
        headers: {
          "Access-Control-Allow-Origin": "*"
        }
      })
      .then(response => response.json())
      .then(data => {
        // Leaflet Karte initialisieren
        var map = L.map('map-container').setView([47.3769, 8.5417], 13);
      
        // Basiskarte hinzufügen
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
          attribution: '© OpenStreetMap contributors'
        }).addTo(map);
      
        // GeoJSON-Daten zur Karte hinzufügen
        L.geoJSON(data).addTo(map);
      })
      .catch(error => console.log('Fehler beim Laden des GeoJSON:', error));*/
    });
    
    
    