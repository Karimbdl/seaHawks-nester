from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os
import json  # Importez le module json

app = Flask(__name__)

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
    last_scan = db.Column(db.String(500), nullable=True) # Garder en String pour JSON
    is_connected = db.Column(db.Boolean, default=False)
    last_seen = db.Column(db.DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<Sonde {self.hostname} ({self.ip_address})>"

# Créer la base de données (à exécuter une seule fois)
with app.app_context():
    db.create_all()

# Route API pour recevoir les données de scan du client
@app.route('/api/sonde', methods=['POST'])
def receive_sonde_data():
    data = request.get_json()
    if not data:
        return jsonify({"message": "Aucune donnée JSON reçue"}), 400

    ip_address = data.get('ip_address')
    hostname = data.get('hostname')
    last_scan_json = data.get('last_scan') # Récupérer en JSON string

    if not ip_address or not hostname:
        return jsonify({"message": "Adresse IP et nom d'hôte requis"}), 400

    # Trouver la sonde existante ou en créer une nouvelle
    sonde = Sonde.query.filter_by(ip_address=ip_address).first()
    if sonde:
        sonde.hostname = hostname
        sonde.last_scan = last_scan_json # Enregistrer le JSON string
        sonde.is_connected = True
        sonde.last_seen = datetime.utcnow()
    else:
        sonde = Sonde(ip_address=ip_address, hostname=hostname, last_scan=last_scan_json, is_connected=True)
        db.session.add(sonde)

    db.session.commit()
    return jsonify({"message": "Données de sonde reçues et enregistrées"}), 201 # 201 Created

# Route pour la page d'accueil avec filtres et pagination
@app.route('/')
def index():
    state_filter = request.args.get('state')
    ip_filter = request.args.get('ip')
    page = request.args.get('page', 1, type=int)  # Numéro de page (par défaut : 1)
    per_page = 10  # Nombre de sondes par page

    query = Sonde.query

    # Appliquer les filtres
    if state_filter == "connected":
        query = query.filter(Sonde.is_connected == True)
    elif state_filter == "disconnected":
        query = query.filter(Sonde.is_connected == False)

    if ip_filter:
        query = query.filter(Sonde.ip_address.contains(ip_filter))

    # Pagination
    sondes = query.paginate(page=page, per_page=per_page)
    return render_template('index.html', sondes=sondes)

# Route pour le tableau de bord d'une sonde
from datetime import datetime, timedelta

@app.route('/dashboard')
def dashboard():
    # Données factices pour l'exemple (à remplacer par vos données réelles)
    total_scans = 120
    connected_sondes = 8
    total_sondes = 10
    total_open_ports = 45
    average_ping = 12.5  # en ms

    last_scan_time = (datetime.utcnow() - timedelta(minutes=30)).strftime("%Y-%m-%d %H:%M:%S")
    last_ping_time = (datetime.utcnow() - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")

    # Données pour les graphiques
    scans_dates = ["2023-10-01", "2023-10-02", "2023-10-03", "2023-10-04", "2023-10-05"]
    scans_counts = [10, 20, 15, 25, 30]

    sondes_labels = ["Sonde 1", "Sonde 2", "Sonde 3", "Sonde 4", "Sonde 5"]
    ports_counts = [5, 10, 7, 12, 8]

    # Liste des sondes (maintenant depuis la base de données)
    sondes = Sonde.query.all()

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
        sondes=sondes # Passer les sondes depuis la base de données
    )

# Démarrer l'application
if __name__ == '__main__':
    app.run(debug=True)