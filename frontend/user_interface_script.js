function closePopup() {
    document.getElementById("popupOverlay").classList.add("hidden");
}
document.addEventListener("DOMContentLoaded", function() {
    var map = L.map('map-container', {
        crs: L.CRS.EPSG3857
    }).setView([47.3769, 8.5417], 13);

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
    
    var getLocationMarker = L.marker([47.3769, 8.5417]);
    var gotoLocationMarker = L.marker([47.3769, 8.5417]);

    var crsControl = L.control({ position: 'bottomright' });

    crsControl.onAdd = function (map) {
        var div = L.DomUtil.create('div', 'leaflet-control-coords');
        div.innerHTML = "<strong>Reference system:</strong> EPSG:3857 (WGS84)";
        div.style.background = "white";
        div.style.padding = "5px";
        div.style.borderRadius = "5px";
        div.style.fontSize = "12px";
        div.style.boxShadow = "0px 0px 5px rgba(0,0,0,0.3)";
        return div;
    };

    crsControl.addTo(map);


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


    var markerUser; 
    var clickedLatLng; 


    map.on('click', function(e) {
        clickedLatLng = e.latlng;

        if (markerUser) {
            map.removeLayer(markerUser);
        }

        markerUser = L.marker(clickedLatLng).addTo(map)
            .bindPopup("Your current position:<br>" + clickedLatLng.lat.toFixed(5) + ", " + clickedLatLng.lng.toFixed(5))
            .openPopup();
    });



    
    const layersControl = new L.control.layers({
        "Basiskarte": osmLayer 
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
            alert("please enter right lon/lat!");
        }
        
        gotoLocationMarker.addTo(map)

    });
    
    function showPosition(position) {
        var lat = position.coords.latitude; 
        var lng = position.coords.longitude; 
    
        map.setView([lat, lng], 13);
        getLocationMarker.setLatLng([lat, lng]);
        getLocationMarker.addTo(map)
        line.setLatLngs([gotoLocationMarker.getLatLng(), getLocationMarker.getLatLng()]);
    }

    document.getElementById("getLocationButton").addEventListener("click", function(){
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(showPosition, showError);
          } else {
            document.getElementById("location").innerHTML = "not possible to get geoloc.";
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
    fetch('http://127.0.0.1:5000/data/walk_isochrones_cube.geojson', {
        method: "GET",
        headers: {
          "Access-Control-Allow-Origin": "*"
        }
      })
      .then(response => response.json())
      .then(data => {

      
        // GeoJSON-Daten zur Karte hinzufügen
        L.geoJSON(data).addTo(map);
      })
      .catch(error => console.log('Fehler beim Laden des GeoJSON:', error));
    });
    
    
    