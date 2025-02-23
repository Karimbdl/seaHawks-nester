from flask import Flask, render_template, jsonify, request
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
import os

app = Flask(__name__)

# Configuration de la base de données SQLite avec un chemin absolu
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

# Créer la base de données (à exécuter une seule fois)
with app.app_context():
    db.create_all()

# Route pour la page d'accueil
@app.route('/')
def index():
    sondes = Sonde.query.all()
    return render_template('index.html', sondes=sondes)

# Route pour le tableau de bord d'une sonde
@app.route('/dashboard/<int:sonde_id>')
def dashboard(sonde_id):
    sonde = Sonde.query.get_or_404(sonde_id)
    return render_template('dashboard.html', sonde=sonde)

# API pour recevoir les données du Harvester
@app.route('/api/sonde', methods=['POST'])
def receive_sonde_data():
    data = request.json
    sonde = Sonde.query.filter_by(ip_address=data['ip_address']).first()

    if not sonde:
        sonde = Sonde(ip_address=data['ip_address'], hostname=data['hostname'])
        db.session.add(sonde)

    sonde.last_scan = data['last_scan']
    sonde.is_connected = True
    sonde.last_seen = datetime.utcnow()
    db.session.commit()

    return jsonify({"message": "Données reçues avec succès !"}), 200

# Démarrer l'application
if __name__ == '__main__':
    app.run(debug=True)