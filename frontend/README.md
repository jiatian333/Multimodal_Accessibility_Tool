# 🗺️ Multimodal Accessibility Web Application

This is a browser-based application for visualizing accessibility to public transport stations in Switzerland with the main focus on Zurich. The tool supports **network-wide monomodal isochrones**, **point-based monomodal isochrones** and **point-based multimodal isochrones**, providing insights into spatial accessibility across various transport modes.

Developed as part of a semester project at ETH Zurich.

---

## 🌟 Key Features

- **🚀 Transport Modes Supported:**
  - Walking
  - Cycling
  - Bicycle rental
  - E-scooter rental
  - Car Sharing
  - Private car

- **🔁 Dual Isochrone Modes:**
  - **Static Mode (Network Isochrones):**  
    Precomputed monomodal isochrones for six transport modes, showing accessibility from various locations in Zurich to the nearest public transport station.
  - **Dynamic Mode (Point Isochrones):**  
    Point-based isochrones for train stations across Switzerland.  
    - For **stations within Zurich**, precomputed monomodal isochrones are available.
    - For **stations outside Zurich**, the application computes multimodal isochrones on demand using the backend performance mode.

- **🚉 Station Interaction:**
  - Autocomplete input for station search
  - Clickable station markers
  - Hovering reveals station name
  - Selected station is highlighted and zoomed
  - On-the-fly computation of multimodal isochrones for station outside of Zurich

- **🗺️ Map Features:**
  - Color-coded isochrones
  - Mode selection and layer control
  - Dynamic legend and info popups

---

The web-application `try.html` is hosted by the official server of ETH Zurich for students.
Internet access is required to load external resources (map tiles, WMS layers, API calls).
To explore the web application and its functionality, simply open the following URL in any modern web browser:

🔗 **https://n.ethz.ch/~jiatian/15_min_project/try.html**

---

## 📁 File Structure

try.html                        # Main file for the web-application
north-arrow-2.svg               # North arrow svg, taken from https://publicdomainvectors.org/en/free-clipart/North-arrow/58771.html

