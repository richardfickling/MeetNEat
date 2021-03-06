

from flask import Flask,request,json,jsonify,session,g,_app_ctx_stack, \
        redirect,url_for,flash,render_template,abort
import sqlite3
import urllib2

DATABASE = "/tmp/meet.n.eat"
PLACES_API_KEY = "NOPE"
PLACES_BASE_URL = "https://maps.googleapis.com/maps/api/place/nearbysearch/json?"
DIRECTIONS_BASE_URL = "http://maps.googleapis.com/maps/api/directions/json?"
PLACES_RADIUS = 3000

#### XXX:
####    Veto / approve
####    error message handling from apis
####    lazy direction getting
####    error codes
####    insert/update location helper
####    license
####    other helpers
####    location - sql join


app = Flask(__name__)
app.config.from_object(__name__)


#### Initialization methods ####
def init_db():
    with app.app_context():
        db = get_db()
        with app.open_resource('schema.sql') as f:
            db.cursor().executescript(f.read())
        db.commit()

def get_db():
    top = _app_ctx_stack.top
    if not hasattr(top, 'sqlite_db'):
        top.sqlite_db = sqlite3.connect(app.config['DATABASE'])
    return top.sqlite_db

#### Helpers ####

def count_sessions(db, sessionid, expected_value):
    cur = db.execute('select count(*) from sessions where sessionid = ?',
            (sessionid,))
    if cur.fetchone()[0] == expected_value:
        return True
    return False

def add_location(db, latitude, longitude):
    db.execute('insert into locations (latitude, longitude) values (?, ?)',
            (latitude, longitude))
    rowid = db.execute('select last_insert_rowid()')
    rowid = rowid.fetchone()[0]
    db.commit()
    return rowid

# Process takes a session id, gets the two locations, finds the middle,
#   uses the places API to find places matching "foodtype", put them in
#   destinations table, and returns true
def process(sessionid):
    db = get_db()
    if not count_sessions(db, sessionid, 1):
        return False
    cur = db.execute('select a_location,b_location,food_pref from sessions where \
            sessionid = ?', (sessionid,))
    result = cur.fetchone()
    food_pref = result[2]
    a_location = db.execute('select latitude, longitude from locations where \
            id = ?', (result[0],))
    a_location = a_location.fetchone()
    b_location = db.execute('select latitude, longitude from locations where \
            id = ?', (result[1],))
    b_location = b_location.fetchone()
    center_latitude = (a_location[0] + b_location[0]) / 2
    center_longitude = (a_location[1] + b_location[1]) / 2
    #Update sessions center location
    rowid = add_location(db, center_latitude, center_longitude)
    db.execute('update sessions set center_location = ? where sessionid = ?',
            (rowid, sessionid))
    db.commit()
    url = ("%slocation=%f,%f&radius=%d&types=food&keyword=%s&key=%s&sensor=false" % \
            (PLACES_BASE_URL, center_latitude, center_longitude, PLACES_RADIUS, food_pref, \
            PLACES_API_KEY))
    places = json.loads(urllib2.urlopen(url).read())
    if places['status'] != 'OK':
        print places['status']
        return False
    for place in places["results"][:2]:
        location_latitude = place["geometry"]["location"]["lat"]
        location_longitude = place["geometry"]["location"]["lng"]
        if location_latitude is None or location_longitude is None:
            return False
        a_c_directions_url = ("%sorigin=%f,%f&destination=%f,%f&sensor=false&mode=walking" % \
                (DIRECTIONS_BASE_URL, a_location[0], a_location[1],\
                location_latitude, location_longitude))
        b_c_directions_url = ("%sorigin=%f,%f&destination=%f,%f&sensor=false&mode=walking" % \
                (DIRECTIONS_BASE_URL, b_location[0], b_location[1],\
                location_latitude, location_longitude))
        a_directions = json.loads(urllib2.urlopen(a_c_directions_url).read())
        b_directions = json.loads(urllib2.urlopen(b_c_directions_url).read())
        if a_directions["status"] != "OK" or b_directions["status"] != "OK":
            return False
        # XXX If necessary, I will break this up and (error) handle the fuck out of it
        a_routes = a_directions["routes"][0]
        b_routes = b_directions["routes"][0]
        a_time = a_routes["legs"][0]["duration"]["value"]
        b_time = a_routes["legs"][0]["duration"]["value"]
        a_distance = b_routes["legs"][0]["distance"]["value"]
        b_distance = b_routes["legs"][0]["distance"]["value"]
        row_id = add_location(db, location_latitude, location_longitude)
        db.execute('insert into destinations \
                (sessionid, name, location, a_distance, b_distance, \
                a_time, b_time) \
                values (?, ?, ?, ?, ?, ?, ?)', \
                (sessionid, place["name"], rowid, a_distance, b_distance, \
                a_time, b_time))
    db.commit()
    return True

#### App routing methods ####

@app.route("/")
def hello():
    return "Fuck off\n"

@app.route("/<sessionid>/init", methods = ['POST'])
def api_init(sessionid):
    if request.method == 'POST':
        if request.headers['Content-Type'] == 'application/json':
            latitude = request.json['latitude']
            longitude = request.json['longitude']
            foodtype = request.json['foodtype']
            if latitude is None or \
                    longitude is None or \
                    foodtype is None:
                        #XXX Correct error codes?
                        abort(400)
            db = get_db()
            if not count_sessions(db, sessionid, 0):
                abort(400)
            rowid = add_location(db, latitude, longitude)
            db.execute('insert into sessions (sessionid, a_location, food_pref) values \
                    (?, ?, ?)', (sessionid, rowid, foodtype))
            db.commit()
            return jsonify({"success":sessionid})
        else:
            #XXX Return error code 400
            abort(400)
    else:
        #XXX Return some error code
        abort(400)

@app.route("/<sessionid>/join", methods = ['POST'])
def api_join(sessionid):
    if request.method == 'POST':
        if request.headers['Content-Type'] == 'application/json':
            latitude = request.json['latitude']
            longitude = request.json['longitude']
            if latitude is None or \
                    longitude is None:
                        #XXX Correct error code
                        print "bad location"
                        abort(400)
            db = get_db()
            if not count_sessions(db, sessionid, 1):
                #XXX Correct error code
                print "no session"
                abort(400)
            rowid = add_location(db, latitude, longitude)
            db.execute('update sessions set b_location = ? where sessionid = ?',
                    (rowid, sessionid))
            db.commit()
            # Process!
            if process(sessionid):
                return jsonify({"success":sessionid})
            else:
                #XXX Correct error code
                abort(400)
        else:
            #XXX Correct error code
            abort(400)
    else:
        #XXX Correct error code
        abort(400)

@app.route("/<sessionid>/results", methods = ['GET', 'POST'])
def api_results(sessionid):
    if request.method == 'GET':
        db = get_db()
        if not count_sessions(db, sessionid, 1):
            #XXX Correct error code
            abort(418)
        cur = db.execute('select name, location, a_distance, b_distance, \
                a_time, b_time, a_veto, b_veto, a_approve, b_approve from destinations \
                where sessionid = ?',
                (sessionid,))
        results = {}
        index = 0
        for row in cur.fetchall():
            loc = db.execute('select latitude, longitude from locations where id = ?',
                    (row[1],))
            location = loc.fetchone()
            values = {}
            values["name"] = row[0]
            values["latitude"] = location[0]
            values["longitude"] = location[1]
            values["a_distance"] = row[2]
            values["b_distance"] = row[3]
            values["a_time"] = row[4]
            values["b_time"] = row[5]
            values["a_veto"] = row[6]
            values["b_veto"] = row[7]
            values["a_approve"] = row[8]
            values["b_approve"] = row[9]
            results[index] = values
            index += 1
        if len(results) == 0:
            #XXX Correct error code
            abort(404)
        else:
            return jsonify(results)
    elif request.method == 'POST':
        db = get_db()
        if not count_sessions(db, sessionid, 1):
            #XXX Correct error code
            abort(418)
        # veto/approve by flag
        a_veto = request['a_veto']
        b_veto = request['b_veto']
        a_approve = request['a_approve']
        b_approve = request['b_approve']
        name = request['name']
        if a_veto is not None:
            db.execute('update destinations set a_veto 1 where name = ?',
                    (name))
        if b_veto is not None:
            db.execute('update destinations set b_veto 1 where name = ?',
                    (name))
        if a_approve is not None:
            db.execute('update destinations set a_approve 1 where name = ?',
                    (name))
        if b_approve is not None:
            db.execute('update destinations set b_approve 1 where name = ?',
                    (name))

    else:
        #XXX Return something useful
        abort(400)

#### RUN ####

if __name__ == "__main__":
    init_db()
    app.run(debug=True, host='0.0.0.0', port=80)
