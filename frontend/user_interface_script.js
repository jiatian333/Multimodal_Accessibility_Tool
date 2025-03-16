document.addEventListener("DOMContentLoaded", function() {
    var map = L.map('map-container').setView([47.3769, 8.5417], 13);

    // Basis-Layer hinzufügen
    var osmLayer = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap contributors'
    }).addTo(map);
    
    var marker = L.marker([47.3769, 8.5417]).addTo(map);

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
            marker.setLatLng([lat, lng]);
        } else {
            alert("Bitte gültige Koordinaten eingeben!");
        }
    });
    

  
    /*function showPosition(position) {
        var lat = position.coords.latitude; 
        var lon = position.coords.longitude; 
  
        document.getElementById("location").innerHTML = "Breite: " + lat + "<br> Länge: " + lon;
      }*/
    document.getElementById("getLocationButton").addEventListener("click", function(){
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(showPosition, showError);
          } else {
            document.getElementById("location").innerHTML = "Geolocation wird von diesem Browser nicht unterstützt.";
          }

    });
});