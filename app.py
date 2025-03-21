from flask import Flask, render_template, jsonify, request, redirect, url_for, session
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import json
from collections import Counter, defaultdict  # Import defaultdict
from flask_apscheduler import APScheduler


app = Flask(__name__)
app.secret_key = 'votre_clé_secrète_login'

app.config['SECRET_KEY'] = 'votre_clé_secrète_ici'

# Configuration de la base de données SQLite
basedir = os.path.abspath(os.path.dirname(__file__))
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'db', 'seahawks.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
db = SQLAlchemy(app)

# Modèle de la table "Sondes"
class Sonde(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ip_address = db.Column(db.String(15), nullable=False)
    hostname = db.Column(db.String(100), nullable=False)
    last_scan = db.Column(db.String(500), nullable=True)
    is_connected = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)
    cpu_usage = db.Column(db.Float, nullable=True)  # <-- NOUVELLE COLONNE : Utilisation CPU
    memory_usage = db.Column(db.Float, nullable=True) # <-- NOUVELLE COLONNE : Utilisation Mémoire

    def __repr__(self):
        return f"<Sonde {self.hostname} ({self.ip_address})>"

# Custom Jinja2 filter pour charger du JSON à partir d'une chaîne
def from_json_filter(json_string):
    try:
        return json.loads(json_string) if json_string else {}
    except json.JSONDecodeError:
        return {}

app.jinja_env.filters['from_json'] = from_json_filter

# Initialiser APScheduler
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

# Fonction pour vérifier la connexion des sondes (tâche périodique)
def check_sonde_connections():
    with app.app_context():
        print("Vérification de la connexion des sondes...")
        sondes = Sonde.query.all()
        now = datetime.utcnow()
        for sonde in sondes:
            if sonde.last_seen < now - timedelta(hours=1):
                if sonde.is_connected:
                    sonde.is_connected = False
                    print(f"Sonde {sonde.hostname} ({sonde.ip_address}) marquée comme déconnectée.")
            elif not sonde.is_connected:
                sonde.is_connected = True
                print(f"Sonde {sonde.hostname} ({sonde.ip_address}) réactivée.")
    db.session.commit()
    print("Vérification des sondes terminée.")

scheduler.add_job(id='check_connections', func=check_sonde_connections, trigger='interval', minutes=1)

# Route API pour recevoir les données de scan du client
@app.route('/api/sonde', methods=['POST'])
def receive_sonde_data():
    data = request.get_json()
    if not data:
        return jsonify({"message": "Aucune donnée JSON reçue"}), 400

    ip_address = data.get('ip_address')
    hostname = data.get('hostname')
    last_scan_json = data.get('last_scan')
    resource_usage_json = data.get('resource_usage') # <-- NOUVEAU : Récupérer resource_usage

    if not ip_address or not hostname:
        return jsonify({"message": "Adresse IP et nom d'hôte requis"}), 400

    sonde = Sonde.query.filter_by(ip_address=ip_address).first()
    if sonde:
        sonde.hostname = hostname
        sonde.last_scan = last_scan_json
        sonde.is_connected = True
        sonde.last_seen = datetime.utcnow()

        # --- NOUVEAU : Enregistrer l'utilisation CPU et mémoire ---
        if resource_usage_json: # Vérifier si resource_usage_json est présent
            try:
                resource_usage_data = json.loads(resource_usage_json)
                sonde.cpu_usage = resource_usage_data.get('cpu_percent') # Récupérer cpu_percent
                sonde.memory_usage = resource_usage_data.get('memory_percent') # Récupérer memory_percent
            except json.JSONDecodeError:
                print(f"Erreur JSON lors de la décode de resource_usage pour sonde {hostname} ({ip_address})")
        # --- FIN NOUVEAU : Enregistrer l'utilisation CPU et mémoire ---

    else:
        sonde = Sonde(ip_address=ip_address, hostname=hostname, last_scan=last_scan_json, is_connected=True)
        # --- NOUVEAU : Enregistrer l'utilisation CPU et mémoire (même pour nouvelle sonde) ---
        if resource_usage_json: # Vérifier si resource_usage_json est présent
            try:
                resource_usage_data = json.loads(resource_usage_json)
                sonde.cpu_usage = resource_usage_data.get('cpu_percent') # Récupérer cpu_percent
                sonde.memory_usage = resource_usage_data.get('memory_percent') # Récupérer memory_percent
            except json.JSONDecodeError:
                print(f"Erreur JSON lors de la décode de resource_usage pour nouvelle sonde {hostname} ({ip_address})")
        # --- FIN NOUVEAU : Enregistrer l'utilisation CPU et mémoire ---
        db.session.add(sonde)

    db.session.commit()
    return jsonify({"message": "Données de sonde reçues et enregistrées"}), 201

# Route pour la page d'accueil avec filtres et pagination
@app.route('/index')
def index():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    state_filter = request.args.get('state')
    ip_filter = request.args.get('ip')
    search_term = request.args.get('search')
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = Sonde.query

    if state_filter == "connected":
        query = query.filter(Sonde.is_connected == True)
    elif state_filter == "disconnected":
        query = query.filter(Sonde.is_connected == False)

    if search_term:
        query = query.filter(db.or_(Sonde.hostname.contains(search_term), Sonde.ip_address.contains(search_term)))

    if ip_filter:
        query = query.filter(Sonde.ip_address.contains(ip_filter))

    sondes = query.paginate(page=page, per_page=per_page)
    return render_template('index.html', sondes=sondes)


@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'):
        return redirect(url_for('login'))

    sondes = Sonde.query.all()
    total_sondes = len(sondes)
    connected_sondes = Sonde.query.filter_by(is_connected=True).count()

    total_scans = total_sondes
    total_open_ports = 0
    ports_par_sonde = {}

    for sonde in sondes:
        if sonde.last_scan:
            try:
                last_scan_data = json.loads(sonde.last_scan)
                open_ports_count = 0
                for host_data in last_scan_data.values():
                    if isinstance(host_data, list):
                        open_ports_count += len(host_data)
                total_open_ports += open_ports_count
                ports_par_sonde[sonde.hostname] = open_ports_count
            except json.JSONDecodeError:
                print(f"Erreur JSON pour sonde {sonde.hostname}")

    average_ping = 24.6
    last_scan_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    last_ping_time = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    # --- Données pour "Scans effectués par jour" (garde ce graphique) ---
    scan_date_counts = Counter()
    for sonde in sondes:
        if sonde.last_seen:
            scan_date = sonde.last_seen.strftime('%Y-%m-%d')
            scan_date_counts[scan_date] += 1
    scans_dates = sorted(scan_date_counts.keys())
    scans_counts = [scan_date_counts[date] for date in scans_dates]
    # --- Fin données "Scans effectués par jour" ---

    # --- NOUVEAU : Données pour "Sondes Connectées/Déconnectées (24h)" ---
    connection_history_data = defaultdict(lambda: {'connected': 0, 'disconnected': 0})
    now = datetime.utcnow()
    for i in range(24): # Pour les 24 dernières heures
        hour = now - timedelta(hours=i)
        hour_str = hour.strftime('%H:00') # Format HH:00 pour l'affichage sur l'axe X
        connected_count = 0
        disconnected_count = 0
        for sonde in sondes:
            # Simule un historique (à remplacer par des données réelles si tu as un historique de connexion)
            if sonde.last_seen > hour - timedelta(hours=1): # Considérer comme connecté dans l'heure si last_seen est dans l'heure
                connected_count += 1
            else:
                disconnected_count += 1
        connection_history_data[hour_str]['connected'] = connected_count
        connection_history_data[hour_str]['disconnected'] = disconnected_count

    connection_labels = sorted(connection_history_data.keys()) # Heures pour l'axe X
    connected_counts_history = [connection_history_data[label]['connected'] for label in connection_labels]
    disconnected_counts_history = [connection_history_data[label]['disconnected'] for label in connection_labels]
    # --- Fin données "Sondes Connectées/Déconnectées (24h)" ---

    # --- NOUVEAU : Données pour "Latence Ping Moyenne (24h)" ---
    average_latency_data = {} # Pour stocker la latence moyenne par heure
    now = datetime.utcnow()
    for i in range(24): # Pour les 24 dernières heures
        hour = now - timedelta(hours=i)
        hour_str = hour.strftime('%H:00')
        average_latency_data[hour_str] = average_ping # <--- REMPLACER average_ping par la vraie latence moyenne si tu la suis

    latency_labels_history = sorted(average_latency_data.keys())
    average_latency_history = list(average_latency_data.values())
    # --- Fin données "Latence Ping Moyenne (24h)" ---


    # --- MODIFICATION : Données réelles pour "Utilisation CPU/Mémoire Sondes (24h)" ---
    cpu_usage_data = {}
    memory_usage_data = {}
    now = datetime.utcnow()
    for i in range(24):
        hour = now - timedelta(hours=i)
        hour_str = hour.strftime('%H:00')
        total_cpu_usage = 0
        total_memory_usage = 0
        active_sondes_count = 0 # Compter le nombre de sondes actives (avec des données récentes) pour la moyenne

        for sonde in sondes:
            # Considérer seulement les sondes qui ont été vues dans les dernières 24h (ou une autre condition pertinente)
            if sonde.last_seen > now - timedelta(days=1) and sonde.cpu_usage is not None and sonde.memory_usage is not None:
                total_cpu_usage += sonde.cpu_usage
                total_memory_usage += sonde.memory_usage
                active_sondes_count += 1

        if active_sondes_count > 0:
            cpu_usage_data[hour_str] = total_cpu_usage / active_sondes_count # Calculer la moyenne si au moins une sonde active
            memory_usage_data[hour_str] = total_memory_usage / active_sondes_count # Calculer la moyenne si au moins une sonde active
        else:
            cpu_usage_data[hour_str] = 0 # Mettre 0 si aucune sonde active
            memory_usage_data[hour_str] = 0 # Mettre 0 si aucune sonde active


    cpu_labels_history = sorted(cpu_usage_data.keys())
    cpu_usage_history = list(cpu_usage_data.values())
    memory_labels_history = sorted(memory_usage_data.keys())
    memory_usage_history = list(memory_usage_data.values())
    # --- Fin MODIFICATION : Données réelles "Utilisation CPU/Mémoire Sondes (24h)" ---


    sondes_labels = list(ports_par_sonde.keys())
    ports_counts = list(ports_par_sonde.values())

    return render_template(
        'dashboard.html',
        total_scans=total_scans,
        connected_sondes=connected_sondes,
        total_sondes=total_sondes,
        total_open_ports=total_open_ports, # Inutile pour l'instant
        average_ping=average_ping,
        last_scan_time=last_scan_time,
        last_ping_time=last_ping_time,
        scans_dates=scans_dates,
        scans_counts=scans_counts,
        sondes_labels=sondes_labels, # Inutile pour l'instant
        ports_counts=ports_counts, # Inutile pour l'instant
        sondes=sondes,
        connection_labels=connection_labels,
        connected_counts_history=connected_counts_history,
        disconnected_counts_history=disconnected_counts_history,
        latency_labels_history=latency_labels_history,
        average_latency_history=average_latency_history,
        cpu_labels_history=cpu_labels_history,
        cpu_usage_history=cpu_usage_history, # NOUVEAU : Données réelles utilisation CPU
        memory_labels_history=memory_labels_history,
        memory_usage_history=memory_usage_history # NOUVEAU : Données réelles utilisation mémoire
    )


# --- ROUTES POUR L'AUTHENTIFICATION ET LA PAGE DE LOGIN ---

# Route pour la page d'accueil (AFFICHE LA PAGE LOGIN directement sur la racine '/')  <--- CHANGEMENT : Page d'accueil AFFICHE LOGIN
@app.route('/')
def home():
    return render_template('login.html') # Renders login page directly


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'] 
        password = request.form['password'] 

        
        if username == 'testuser' and password == 'password': 
            session['logged_in'] = True 
            return redirect(url_for('dashboard')) 
        else:
            error = 'Invalid credentials. Please try again.' 
            return render_template('login.html', error=error) 

    return render_template('login.html') 

@app.route('/logout')
def logout():
    session.pop('logged_in', None) # Clear the 'logged_in' session variable
    return redirect(url_for('login')) # Redirect to login page after logout


# --- ROUTES POUR LA CONFIGURATION DES SONDES ---

# --- AJOUTER CE BLOC POUR METTRE A JOUR LA BASE DE DONNEES ---
# --- AJOUTER CE BLOC POUR METTRE A JOUR LA BASE DE DONNEES AVEC DEBUG LOGS ---
print("--- Début de db.create_all() ---") # AJOUTER : Log de début
with app.app_context():
    print("--- app.app_context() créé ---") # AJOUTER : Log après app_context
    db.create_all()
    print("--- db.create_all() exécuté ---") # AJOUTER : Log après db.create_all
print("--- Fin de db.create_all() ---") # AJOUTER : Log de fin
# --- FIN AJOUTER CE BLOC POUR METTRE A JOUR LA BASE DE DONNEES AVEC DEBUG LOGS ---
# --- FIN AJOUTER CE BLOC POUR METTRE A JOUR LA BASE DE DONNEES ---


# Démarrer l'application
if __name__ == '__main__':
    app.run(debug=True)