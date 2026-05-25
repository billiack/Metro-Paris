import streamlit as st
import plotly.graph_objects as go
from pathlib import Path
from datetime import time as dtime
from preprocess import load_preprocessed_gtfs
from graph.models import Graph
from graph.algorithms import is_connected, kruskal, dijkstra_v3

st.set_page_config(page_title="Métro Paris", layout="wide")
st.title("Métro Paris")

@st.cache_resource(show_spinner="Chargement du graphe...")
def load_graph():
    base = Path(__file__).resolve().parent
    gz_path = base / "GTFS_preprocessed.json.gz" # Prend moins d'espace disque mais est plus lent à charger
    json_path = base / "GTFS_preprocessed.json" # Plus rapide à charger mais prend beaucoup plus d'espace disque.
    input_path = gz_path if gz_path.exists() else json_path
    preprocessed = load_preprocessed_gtfs(input_path)
    return Graph.from_preprocessed(preprocessed)

g = load_graph()

name_counts = {}
for station in g.stations.values():
    name_counts[station.name] = name_counts.get(station.name, 0) + 1

station_options = []
for sid, station in g.stations.items():
    label = station.name

    # Si plusieurs stations ont le même nom, on ajoute la ligne pour les différencier
    if name_counts[station.name] > 1:
        line = station.line.strip() if station.line else "?"
        label = f"{station.name} ({line})"
    station_options.append((label, sid))

station_options.sort(key=lambda item: item[0])
station_labels = [label for label, _ in station_options]
label_to_id = dict(station_options)

def line_color(line):
    return g.route_colors.get(str(line).upper().replace('M', ''), '#888888')

def sec_to_hhmm(s):
    s = int(s) % 86400
    return f"{s // 3600:02d}h{(s % 3600) // 60:02d}"


def station_hover_text(station):
    if station.routes:
        return f"{station.name} — {', '.join(station.routes)}"
    return station.name

def build_map(g, highlight_path=None, highlight_acpm=None, acpm_steps=None):
    fig = go.Figure()

    line_data = {}
    seen = set()
    for na, voisins in g.adjacency.items():
        for nb, _ in voisins:
            key = (min(na, nb), max(na, nb))
            if key in seen:
                continue
            seen.add(key)
            sa, sb = g.stations[na], g.stations[nb]
            lk = g.edge_route_short_names.get((na, nb)) or g.edge_route_short_names.get((nb, na)) or sa.line
            if lk not in line_data:
                line_data[lk] = {'lats': [], 'lons': []}
            line_data[lk]['lats'].extend([sa.lat, sb.lat, None])
            line_data[lk]['lons'].extend([sa.lon, sb.lon, None])

    for line, data in line_data.items():
        fig.add_trace(go.Scattermapbox(
            lat=data['lats'], lon=data['lons'], mode='lines',
            line=dict(width=2, color=line_color(line)),
            hoverinfo='none', showlegend=False,
        ))

    if highlight_acpm:
        lats, lons = [], []
        for na, nb, _ in (highlight_acpm[:acpm_steps] if acpm_steps else highlight_acpm):
            sa, sb = g.stations[na], g.stations[nb]
            lats.extend([sa.lat, sb.lat, None])
            lons.extend([sa.lon, sb.lon, None])
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode='lines',
            line=dict(width=4, color='#FF3333'),
            hoverinfo='none', showlegend=False,
        ))

    if highlight_path and len(highlight_path) > 1:
        lats, lons = [], []
        for i in range(len(highlight_path) - 1):
            sa, sb = g.stations[highlight_path[i]], g.stations[highlight_path[i + 1]]
            lats.extend([sa.lat, sb.lat, None])
            lons.extend([sa.lon, sb.lon, None])
        fig.add_trace(go.Scattermapbox(
            lat=lats, lon=lons, mode='lines',
            line=dict(width=5, color='#00DD88'),
            hoverinfo='none', showlegend=False,
        ))

    path_set = set(highlight_path) if highlight_path else set()
    fig.add_trace(go.Scattermapbox(
        lat=[s.lat for s in g.stations.values()],
        lon=[s.lon for s in g.stations.values()],
        mode='markers',
        marker=dict(
            size=[10 if sid in path_set else 7 for sid in g.stations],
            color=['#00DD88' if sid in path_set else line_color(g.stations[sid].line) for sid in g.stations],
        ),
        text=[station_hover_text(s) for s in g.stations.values()],
        hoverinfo='text', showlegend=False,
    ))

    fig.update_layout(
        mapbox=dict(style='open-street-map', center=dict(lat=48.8566, lon=2.3522), zoom=11),
        margin=dict(l=0, r=0, t=0, b=0), height=900,
    )
    return fig


tab1, tab2, tab3, tab4 = st.tabs(["Réseau", "Itinéraire", "ACPM", "Connexité"])

with tab1:
    st.plotly_chart(build_map(g), use_container_width=True, key="full_map")

with tab2:
    col1, col2 = st.columns(2)
    depart_label = col1.selectbox("Départ", station_labels)
    arrivee_label = col2.selectbox("Arrivée", station_labels, index=min(10, len(station_labels) - 1))
    heure = st.time_input("Heure de départ", value=dtime(8, 0))

    if st.button("Calculer", type="primary"):
        start_id, end_id = label_to_id[depart_label], label_to_id[arrivee_label]
        if start_id == end_id:
            st.warning("Départ et arrivée identiques.")
        else:
            with st.spinner("Calcul..."):
                dep_sec = heure.hour * 3600 + heure.minute * 60
                path, arrival, details = dijkstra_v3(g, start_id, end_id, dep_sec)
            if not path:
                st.error("Aucun itinéraire trouvé.")
            else:
                if details[0]['wait'] - dep_sec > 3600:
                    st.warning("Premier départ dans plus d'une heure.")
                total = arrival - dep_sec
                st.success(f"Arrivée : **{sec_to_hhmm(arrival)}** - Durée : **{total // 60} min**")

                segments = []
                cur = None
                for d in details:
                    if d.get('kind') != 'ride':
                        continue
                    line = d.get('line')
                    if cur is None:
                        cur = {
                            'line': line,
                            'from_name': d['from_name'],
                            'to_name': d['to_name'],
                            'departure': d['departure'],
                            'arrival': d['arrival'],
                        }
                    elif line == cur['line']:
                        cur['to_name'] = d['to_name']
                        cur['arrival'] = d['arrival']
                    else:
                        segments.append(cur)
                        cur = {
                            'line': line,
                            'from_name': d['from_name'],
                            'to_name': d['to_name'],
                            'departure': d['departure'],
                            'arrival': d['arrival'],
                        }
                if cur is not None:
                    segments.append(cur)

                if not segments:
                    st.info("Aucun segment de trajet trouvé.")
                else:
                    for s in segments:
                        mins = max(0, int(s['arrival']) - int(s['departure'])) // 60
                        st.write(f"{s['line']} - {s['from_name']} ({sec_to_hhmm(s['departure'])}) -> {s['to_name']} ({sec_to_hhmm(s['arrival'])}) - ({mins}min)")
                st.plotly_chart(build_map(g, highlight_path=path), use_container_width=True, key="path_map")

with tab3:
    if st.button("Calculer l'ACPM", type="primary"):
        with st.spinner("Kruskal en cours..."):
            acpm, poids = kruskal(g)
        st.session_state['acpm'] = acpm
        st.session_state['acpm_poids'] = poids

    if 'acpm' in st.session_state:
        acpm, poids = st.session_state['acpm'], st.session_state['acpm_poids']
        st.success(f"**{len(acpm)} arêtes** — Poids total : **{poids // 60} min**")
        step = st.slider("Propagation", 1, len(acpm), len(acpm))
        st.plotly_chart(build_map(g, highlight_acpm=acpm, acpm_steps=step), use_container_width=True, key="acpm_map")

with tab4:
    if st.button("Verifier", type="primary"):
        connexe, non_atteints = is_connected(g)
        if connexe:
            st.success(f"Reseau connexe — {len(g.stations)} stations accessibles")
        else:
            st.error(f"Non connexe — {len(non_atteints)} stations isolees")
        st.plotly_chart(build_map(g), use_container_width=True, key="connexite_map")
