import atexit  # Dodano za pokretanje funkcije pri izlazu
import threading
from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, and_, asc, desc
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime, timedelta
import socket
import re
from flask_session import Session
import json



app = Flask(__name__)
# Konfiguracija Flask-Session
app.config['SESSION_TYPE'] = 'filesystem'  # Može se koristiti 'redis', 'memcached', 'filesystem' itd.
app.config['SECRET_KEY'] = 'mario123'  # Tajni ključ za zaštitu sesije
Session(app)  # Inicijaliziraj sesiju
app.config['SESSION_COOKIE_SECURE'] = False  # Osiguraj da se kolačići šalju samo preko HTTPS-a
app.config['SESSION_COOKIE_HTTPONLY'] = False  # Spriječava pristup kolačićima iz JavaScript-a
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)  # Maksimalno trajanje sesije od 30 minuta


# Globalna promenljiva za praćenje statusa prijave
logged_in = False

# Konfiguracija baze
DATABASE_URI = 'sqlite:///aprs_sonde.db'
engine = create_engine(DATABASE_URI)
Base = declarative_base()
Session = sessionmaker(bind=engine)
Base.metadata.create_all(engine)
session = Session()

class APRSSonde(Base):
    __tablename__ = 'aprs_sonde'
    id = Column(Integer, primary_key=True)
    callsign = Column(String)
    latitude = Column(Float)
    longitude = Column(Float)
    altitude = Column(Integer)
    timestamp = Column(DateTime)
    climb = Column(Float)
    direction = Column(Integer)
    speed = Column(Float)
    last_RX = Column(String)
    frequency = Column(Float)



# Podaci za povezivanje APRS prijemnika(prijemnih stanica)
HOST = '0.0.0.0'
PORT = 14580

def send_data(client_socket, data):
    response = f"{data}"
    client_socket.sendall(response.encode('utf-8'))

def add_data(callsign, latitude, longitude, altitude, timestamp, climb, direction, speed, frequency, last_RX):
    session = Session()
    existing_record = session.query(APRSSonde).filter_by(callsign=callsign).first()
    try:
        if existing_record:
            # Ažuriraj samo ako su podaci stari manje od minute
            # if (timestamp - existing_record.timestamp).total_seconds() < 60:
                existing_record.latitude = latitude
                existing_record.longitude = longitude
                existing_record.altitude = altitude
                existing_record.timestamp = timestamp
                existing_record.climb = climb
                existing_record.direction = direction
                existing_record.speed = speed
                existing_record.last_RX = last_RX
                existing_record.frequency = frequency
                session.commit()
                print(f"Ažurirani podaci za {callsign} u {timestamp}")
        else:
            new_record = APRSSonde(
                callsign=callsign, latitude=latitude, longitude=longitude,
                altitude=altitude, timestamp=timestamp, climb=climb,
                direction=direction, speed=speed, last_RX=last_RX, frequency=frequency
            )
            session.add(new_record)
            session.commit()
            print(f"Dodani podaci za {callsign} u {timestamp}")
    except Exception as e:
        print(f"Greška: {e}")
        session.rollback()  # Vrati sve promjene unazad
    finally:
        session.close()  # Uvijek zatvori sesiju na kraju



def handle_client(client_socket):
    """ Funkcija za rukovanje pojedinačnom konekcijom. """
    try:
        while True:
            data = client_socket.recv(1024).decode('utf-8')
            if not data:
                break

            print(f"Primljen paket: {data}")

            # Izvlačenje `callsign_station` (prvi dio prije znaka `>`)
            callsign_station_match = re.search(r"^(\S+)>", data)
            callsign_station = callsign_station_match.group(1) if callsign_station_match else "unknown"

            if "user" in data:
                send_data(client_socket, "# 9A4AM v0.0.1.15\r\n")
                send_data(client_socket, f"# logresp {callsign_station} unverified, server 9A4AM v0.0.1.15\r\n")
            else:
                send_data(client_socket, "Invalid packet")

            try:
                # Parsiranje `callsign`
                match1 = re.search(r";([A-Za-z0-9]+)", data)
                callsign = match1.group(1) if match1 else None

                # Parsiranje last_RX na početku paketa
                match_rx = re.match(r"(\S+)>", data)
                if match_rx:
                    last_RX = match_rx.group(1)
                    print(f"last_RX: {last_RX}")
                else:
                    print("Podatak last_RX nije pronađen.")

                # Parsiranje frekvencije
                match_frequency = re.search(r"(\d+\.\d{2,3})\s?MHz", data)

                # Proverite da li je razmak između broja i "MHz"
                if match_frequency and match_frequency.group(0)[-3:] == "MHz":
                    frequency = float(match_frequency.group(1))
                    print(f"Frekvencija: {frequency} MHz")
                else:
                    frequency = float("0.0")
                    print("Frekvencija u paketu nije pronađena ili je neispravan paket.")

                # Parsiranje `station_rx` koordinata (latitude i longitude) desno od `:!`
                station_rx_match = re.search(r":!(\d{2})(\d{2}\.\d{2})N/(\d{3})(\d{2}\.\d{2})E", data)
                if station_rx_match:
                    # Pretvaranje latitude i longitude u decimalni oblik
                    latitude_rx = round(float(station_rx_match.group(1)) + float(station_rx_match.group(2)) / 60.0, 4)
                    longitude_rx = round(float(station_rx_match.group(3)) + float(station_rx_match.group(4)) / 60.0, 4)
                    timestamp = datetime.now()
                    # Učitaj sve trenutne podatke iz datoteke
                    updated_stations = []
                    station_found = False
                    try:
                        with open("active_stations.txt", "r") as file:
                            for line in file:
                                parts = line.strip().split(',')
                                if len(parts) == 4:
                                    existing_callsign, latitude, longitude, existing_timestamp = parts
                                    if existing_callsign == callsign_station:
                                        # Ažuriraj postojeći zapis
                                        updated_stations.append(f"{callsign_station},{latitude_rx},{longitude_rx},{timestamp}\n")
                                        station_found = True
                                    else:
                                        # Zadrži ostale zapise kako jesu
                                        updated_stations.append(line)
                    except FileNotFoundError:
                        pass  # Ako datoteka ne postoji, samo nastavi - kreirat će se nova

                    # Ako pozivni znak nije pronađen, dodaj novi zapis
                    if not station_found and callsign_station != "unknown":
                        updated_stations.append(f"{callsign_station},{latitude_rx},{longitude_rx},{timestamp}\n")

                    # Zapiši sve ažurirane podatke nazad u fajl
                    with open("active_stations.txt", "w") as file:
                        file.writelines(updated_stations)



                    print(f"Podaci za stanicu {callsign_station}.")
                    print(f"Stanica pozivni znak: {callsign_station}")
                    print(f"Stanica kordinate (decimal): Latitude: {latitude_rx}, Longitude: {longitude_rx}")

                # Parsiranje latitude, longitude, altitude za `sonde`
                match = re.search(r"(\d+\.\d{2})N/(\d+\.\d{2})EO.*A=(\d+)", data)
                if match:
                    latitude = round(float(match.group(1)[:2]) + float(match.group(1)[2:]) / 60.0, 4)
                    longitude = round(float(match.group(2)[:3]) + float(match.group(2)[3:]) / 60.0, 4)
                    altitude = round(int(match.group(3)) * 0.3048)  # m
                    timestamp = datetime.utcnow()

                    # Dodatni podaci
                    match_climb = re.search(r"Clb=(-?\d+\.\d+)", data)
                    match_direction_speed = re.search(r"(\d{3})/(\d{3})/A", data)
                    climb = float(match_climb.group(1)) if match_climb else None
                    direction = int(match_direction_speed.group(1)) if match_direction_speed else None
                    speed = round(float(match_direction_speed.group(2)) * 1.852, 1) if match_direction_speed else None

                    # Spremanje podataka
                    add_data(callsign, latitude, longitude, altitude, timestamp, climb, direction, speed, frequency, last_RX)
                else:
                    print("Latitude/Longitude/Altitude podaci nisu ispravni ili ne postoje.")

            except Exception as e:
                print(f"Greška parsiranja podataka: {e}")

    except Exception as e:
        print(f"Greška rukovanja klijentom: {e}")
    finally:
        client_socket.close()


# Funkcija koja se izvršava na izlazu programa
def close_resources():
    print("Izvršava se čišćenje resursa...")
    # Dodajte kod za zatvaranje konekcija, čišćenje sesija itd.
    # Zatvori konekciju sa sesijom baze podataka
    session = Session()
    session.close()
    print("Konekcija s bazom je zatvorena.")

# Registriramo `close_resources` da se pozove pri izlazu iz programa
atexit.register(close_resources)




def aprs_listener():
    """ Glavna funkcija za slušanje dolaznih APRS podataka i pokretanje niti za svaku konekciju. """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server_socket:
        server_socket.bind((HOST, PORT))
        server_socket.listen()
        print(f"APRS server pokrenut na {HOST}:{PORT}")

        while True:
            client_socket, addr = server_socket.accept()
            print(f"Spaja se: {addr}")
            client_thread = threading.Thread(target=handle_client, args=(client_socket,))
            client_thread.start()

@app.route('/', methods=['GET', 'POST'])
def login():
    global logged_in  # Oznaka da ćemo koristiti globalnu promenljivu
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username == 'user' and password == 'password':
            logged_in = True  # Postavi status prijave
            return redirect(url_for('index'))
        else:
            flash("Neispravno korisničko ime ili lozinka.")
            return render_template('login.html')

    return render_template('login.html')




@app.route('/index')
def index():
    print("Inicijalizacija funkcije index()")  # Ovo će pokazati da je funkcija pokrenuta
    global logged_in  # Oznaka da ćemo koristiti globalnu promenljivu

    if not logged_in:  # Provjeri status prijave
        flash("Molimo prijavite se.")
        return redirect(url_for('login'))

    # Pozivanje funkcije za čišćenje neaktivnih prijemnih stanica
    print("Pozivanje cleanup_inactive_stations()")
    cleanup_inactive_stations()

    try:
        hours = request.args.get('hours', default=6, type=int)
        time_threshold = datetime.utcnow() - timedelta(hours=hours)

        print(f"Vremenski prag: {time_threshold}")
        results = session.query(APRSSonde).filter(APRSSonde.timestamp >= time_threshold).all()
        print(f"Rezultati iz baze: {results}")  # Proverava koje rezultate dobijate iz baze

        sondes = [
            {
                'callsign': row.callsign,
                'latitude': f"{row.latitude:.4f}",
                'longitude': f"{row.longitude:.4f}",
                'altitude': row.altitude,
                'timestamp': row.timestamp,
                'climb': row.climb,
                'speed': row.speed,
                'direction': row.direction,
                'last_RX': row.last_RX,
                'frequency': row.frequency
            }
            for row in results
        ]

        print(f"Podaci o sondama: {sondes}")  # Provjerava podatke o sondama

        # Učitavanje podataka o prijemnim stanicama iz tekstualne datoteke
        active_stations = []
        try:
            print("Učitavanje aktivnih stanica iz datoteke...")
            with open("active_stations.txt", "r") as file:
                for line in file:
                    print(f"Čitanje linije: {line.strip()}")  # Prikazivanje linije koja se čita
                    parts = line.strip().split(',')
                    if len(parts) == 4:
                        callsign, latitude, longitude, timestamp_str = parts
                        active_stations.append({
                            'callsign': callsign,
                            'latitude': latitude,
                            'longitude': longitude,
                            'last_seen': timestamp_str
                        })
                    else:
                        print(f"Neispravan format linije: {line.strip()}")  # Ispis za neispravan format
        except FileNotFoundError:
            flash("Datoteka s podacima o aktivnim stanicama nije pronađena.")
            print("Datoteka nije pronađena.")  # Ispis poruke kada fajl nije pronađen

        print(f"Aktivne prijemne stanice: {active_stations}")  # Prikazivanje svih aktivnih stanica

        # Vraćanje rezultata
        return render_template('index.html', sondes=sondes, results=results, active_stations=active_stations, stations=json.dumps(active_stations))

    except Exception as e:
        # Logiraj grešku u terminal
        print(f"Greška se dogodila: {e}")
        # Prikažite korisniku prijateljsku poruku
        flash("Došlo je do greške pri dohvaćanju podataka. Molimo pokušajte ponovo kasnije.")
        return render_template('error.html'), 500  # Prikaz stranice greške sa statusom 500


@app.route('/sondes_data')
def sondes_data():
    try:
        time_threshold = datetime.utcnow() - timedelta(hours=6)
        sondes = [
            {
                'callsign': row.callsign,
                'latitude': f"{row.latitude:.4f}",
                'longitude': f"{row.longitude:.4f}",
                'altitude': row.altitude,
                'timestamp': row.timestamp,
                'climb': row.climb,
                'speed': row.speed,
                'direction': row.direction,
                'last_RX': row.last_RX,
                'frequency': row.frequency
            }
            for row in session.query(APRSSonde).filter(APRSSonde.timestamp >= time_threshold).all()
        ]
        # print("Podaci o sondi uspješno dohvačeni:", sondes)
        return jsonify(sondes)
    except Exception as e:
        print(f"Greška dohvaćanja podataka /sondes_data route: {e}")
        return jsonify({"error": "Dogodila se greška u dohvaćanju podataka"}), 500





@app.route('/sondes', methods=['GET'])
def filter_sondes():
    try:
        callsign = request.args.get('callsign')
        start_time = request.args.get('start_time')
        end_time = request.args.get('end_time')
        sort_by = request.args.get('sort_by', 'timestamp')  # Zadano sortiranje po vremenu

        query = session.query(APRSSonde)

        if callsign:
            query = query.filter(APRSSonde.callsign == callsign)
        elif start_time and end_time:
            start_time_dt = datetime.fromisoformat(start_time)
            end_time_dt = datetime.fromisoformat(end_time)
            query = query.filter(and_(APRSSonde.timestamp >= start_time_dt, APRSSonde.timestamp <= end_time_dt))
        else:
            # Postavi vremenski prag na zadnjih 6 sati ako nije zadano
            time_threshold = datetime.utcnow() - timedelta(hours=6)
            query = query.filter(APRSSonde.timestamp >= time_threshold)

        # Primijeni sortiranje prema odabiru
        if sort_by == 'altitude':
            query = query.order_by(asc(APRSSonde.altitude))
        else:
            query = query.order_by(desc(APRSSonde.timestamp))

        results = query.all()

        # Prikupi podatke za prikaz u JSON obliku
        sondes = [
            {
                'callsign': row.callsign,
                'latitude': row.latitude,
                'longitude': row.longitude,
                'altitude': row.altitude,
                'timestamp': row.timestamp,
                'climb': row.climb,
                'speed': row.speed,
                'direction': row.direction,
                'last_RX': row.last_RX,
                'frequency': row.frequency
            }
            for row in results
        ]

        # Učitavanje podataka o stanicama iz tekstualnog fajla
        active_stations = []
        try:
            with open("active_stations.txt", "r") as file:
                for line in file:
                    parts = line.strip().split(',')
                    if len(parts) == 4:
                        callsign, latitude, longitude, timestamp_str = parts
                        active_stations.append({
                            'callsign': callsign,
                            'latitude': latitude,
                            'longitude': longitude,
                            'last_seen': timestamp_str
                        })
        except FileNotFoundError:
            flash("Datoteka s podacima o aktivnim stanicama nije pronađena.")

        return render_template('filter.html', sondes=sondes, results=results, active_stations=active_stations, stations=json.dumps(active_stations))

    except Exception as e:
        print(f"Error in filter_sondes route: {e}")
        return jsonify({"error": "Greška dohvaćanja podataka"}), 500



@app.route('/sondes24')
def filter24():
    try:
        hours = request.args.get('hours', default=6, type=int)
        time_threshold = datetime.utcnow() - timedelta(hours=hours)
        results = session.query(APRSSonde).filter(APRSSonde.timestamp >= time_threshold).all()
        print(time_threshold)

        sondes = [
            {
                'callsign': row.callsign,
                'latitude': row.latitude,
                'longitude': row.longitude,
                'altitude': row.altitude,
                'timestamp': row.timestamp,
                'climb': row.climb,
                'speed': row.speed,
                'direction': row.direction,
                'last_RX': row.last_RX,
                'frequency': row.frequency
            }
            for row in results
        ]

        # Učitavanje podataka o stanicama iz tekstualnog fajla
        active_stations = []
        try:
            with open("active_stations.txt", "r") as file:
                for line in file:
                    parts = line.strip().split(',')
                    if len(parts) == 4:
                        callsign, latitude, longitude, timestamp_str = parts
                        active_stations.append({
                            'callsign': callsign,
                            'latitude': latitude,
                            'longitude': longitude,
                            'last_seen': timestamp_str
                        })
        except FileNotFoundError:
            flash("Datoteka s podacima o aktivnim stanicama nije pronađena.")

        return render_template(
            'filter.html',
            sondes=sondes,
            results=results,
            active_stations=active_stations,
            stations=json.dumps(active_stations),
            hours=hours
        )

    except Exception as e:
        # Logiraj grešku u terminal
        print(f"Greška: {e}")
        # Prikažite korisniku prijateljsku poruku
        flash("Došlo je do greške pri dohvaćanju podataka. Molimo pokušajte ponovo kasnije.")
        return render_template('error.html'), 500  # Prikaz stranice greške sa statusom 500

# Funkcija za provjeru i čišćenje neaktivnih stanica
def cleanup_inactive_stations():
    six_hours_ago = datetime.now() - timedelta(hours=6)
    updated_data = []

    # Čitanje i filtriranje aktivnih stanica
    with open("active_stations.txt", "r") as file:
        for line in file:
            callsign_station, latitude, longitude, timestamp_str = line.strip().split(',')
            timestamp = datetime.fromisoformat(timestamp_str)
            if timestamp > six_hours_ago:
                updated_data.append(line)

    # Ažuriranje fajla samo s aktivnim stanicama
    with open("active_stations.txt", "w") as file:
        file.writelines(updated_data)



@app.errorhandler(500)
def internal_error(error):
    return render_template("error.html"), 500



if __name__ == "__main__":
    aprs_thread = threading.Thread(target=aprs_listener)
    aprs_thread.start()
    app.run(debug=False, host='0.0.0.0', port=80)
