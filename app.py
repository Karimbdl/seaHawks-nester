from flask import Flask, render_template, jsonify, request, redirect, url_for, session # <-- Importer session et redirect
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta
import os
import json
from collections import Counter
from flask_apscheduler import APScheduler


app = Flask(__name__)
app.secret_key = 'votre_clé_secrète_login'  # Clé secrète pour les sessions - IMPORTANT, changez ça!


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

    def __repr__(self):
        return f"<Sonde {self.hostname} ({self.ip_address})>"

# Custom Jinja2 filter pour charger du JSON à partir d'une chaîne
def from_json_filter(json_string):
    try:
        return json.loads(json_string) if json_string else {}  # Retourne un dict vide si None
    except json.JSONDecodeError:
        return {}  # Retourne un dict vide en cas d'erreur

app.jinja_env.filters['from_json'] = from_json_filter  # Enregistre le filtre

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
            # Considérer une sonde comme déconnectée si pas de nouvelles données depuis 1 heure
            if sonde.last_seen < now - timedelta(hours=1):
                if sonde.is_connected:
                    sonde.is_connected = False
                    print(f"Sonde {sonde.hostname} ({sonde.ip_address}) marquée comme déconnectée.")
            elif not sonde.is_connected:
                sonde.is_connected = True
                print(f"Sonde {sonde.hostname} ({sonde.ip_address}) réactivée.")
        db.session.commit()
        print("Vérification des sondes terminée.")

# Planifier la tâche de vérification de connexion (toutes les minutes par exemple)
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

    if not ip_address or not hostname:
        return jsonify({"message": "Adresse IP et nom d'hôte requis"}), 400

    sonde = Sonde.query.filter_by(ip_address=ip_address).first()
    if sonde:
        sonde.hostname = hostname
        sonde.last_scan = last_scan_json
        sonde.is_connected = True
        sonde.last_seen = datetime.utcnow()
    else:
        sonde = Sonde(ip_address=ip_address, hostname=hostname, last_scan=last_scan_json, is_connected=True)
        db.session.add(sonde)

    db.session.commit()
    return jsonify({"message": "Données de sonde reçues et enregistrées"}), 201

# Route pour la page d'accueil avec filtres et pagination
@app.route('/index')
def index():
    if not session.get('logged_in'): # <---- AJOUTER : Protection du dashboard, nécessite login
        return redirect(url_for('login')) # <---- AJOUTER : Redirige vers login si non connecté

    state_filter = request.args.get('state')
    ip_filter = request.args.get('ip')
    search_term = request.args.get('search') # Récupérer le terme de recherche
    page = request.args.get('page', 1, type=int)
    per_page = 10

    query = Sonde.query

    # Filtrer par état
    if state_filter == "connected":
        query = query.filter(Sonde.is_connected == True)
    elif state_filter == "disconnected":
        query = query.filter(Sonde.is_connected == False)

    # Filtrer par terme de recherche (nom d'hôte ou IP)
    if search_term:
        query = query.filter(db.or_(Sonde.hostname.contains(search_term), Sonde.ip_address.contains(search_term)))

    if ip_filter:
        query = query.filter(Sonde.ip_address.contains(ip_filter))

    sondes = query.paginate(page=page, per_page=per_page)
    return render_template('index.html', sondes=sondes)

# Route pour le tableau de bord d'une sonde
@app.route('/dashboard')
def dashboard():
    if not session.get('logged_in'): # <---- AJOUTER : Protection du dashboard, nécessite login
        return redirect(url_for('login')) # <---- AJOUTER : Redirige vers login si non connecté

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

    average_ping = 12.5
    last_scan_time = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    last_ping_time = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    scans_dates = ["2023-10-01", "2023-10-02", "2023-10-03", "2023-10-04", "2023-10-05"]
    scans_counts = [10, 20, 15, 25, 30]

    sondes_labels = list(ports_par_sonde.keys())
    ports_counts = list(ports_par_sonde.values())

    return render_template(
        'dashboard.html',
        total_scans=total_scans,
        connected_sondes=connected_sondes,
        total_sondes=total_sondes,
        total_open_ports=total_open_ports,
        average_ping=average_ping,
        last_scan_time=last_scan_time,
        last_ping_time=last_ping_time,
        scans_dates=scans_dates,
        scans_counts=scans_counts,
        sondes_labels=sondes_labels,
        ports_counts=ports_counts,
        sondes=sondes
    )

# --- ROUTES POUR L'AUTHENTIFICATION ET LA PAGE DE LOGIN ---

# Route pour la page d'accueil (AFFICHE LA PAGE LOGIN directement sur la racine '/')  <--- CHANGEMENT : Page d'accueil AFFICHE LOGIN
@app.route('/')
def home():
    return render_template('login.html') # Renders login page directly


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username'] # Assumes you have a username field in your form
        password = request.form['password'] # Assumes you have a password field

        # --- BASIQUE : Hardcoded credentials - REMPLACER PAR UN VRAI SYSTEME D'AUTH PLUS TARD ---
        if username == 'testuser' and password == 'password': # Exemple credentials
            session['logged_in'] = True # Set a session variable to indicate login
            return redirect(url_for('dashboard')) # Redirect to dashboard after login
        else:
            error = 'Invalid credentials. Please try again.' # Error message for invalid login
            return render_template('login.html', error=error) # Render login page with error

    return render_template('login.html') # Render login page for GET request

@app.route('/logout')
def logout():
    session.pop('logged_in', None) # Clear the 'logged_in' session variable
    return redirect(url_for('login')) # Redirect to login page after logout


# --- ROUTES POUR LA CONFIGURATION DES SONDES ---


# Démarrer l'application
if __name__ == '__main__':
    app.run(debug=True)