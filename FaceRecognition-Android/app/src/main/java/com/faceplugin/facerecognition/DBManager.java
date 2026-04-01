package com.faceplugin.facerecognition;

import android.content.ContentValues;
import android.content.Context;
import android.database.Cursor;
import android.database.sqlite.SQLiteDatabase;
import android.database.sqlite.SQLiteOpenHelper;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;

import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.UUID;

public class DBManager extends SQLiteOpenHelper {

    public static ArrayList<Person> personList = new ArrayList<Person>();

    public DBManager(Context context) {
        super(context, "mydb" , null, 12);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        // TODO Auto-generated method stub
        db.execSQL(
                "create table person " +
                        "(local_uid text, id text, name text, face blob, templates blob, phone text, department text, designation text, shift text, custom_data text, synced integer default 1)"
        );
        db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS idx_person_local_uid ON person(local_uid)");
        db.execSQL(
                "create table attendance_queue " +
                        "(id integer primary key autoincrement, person_id text, local_uid text, name text, timestamp text, status text, image blob, is_late integer)"
        );
        db.execSQL(
                "create table attendance_state " +
                        "(id_key text primary key, person_id text, local_uid text, name text, last_status text, last_timestamp text)"
        );
        db.execSQL(
                "create table delete_queue " +
                        "(id integer primary key autoincrement, person_id text, local_uid text, name text, created_at text)"
        );
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        if (oldVersion < 8) {
            try {
                db.execSQL("ALTER TABLE person ADD COLUMN local_uid text");
            } catch (Exception ignored) {}
            try {
                db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS idx_person_local_uid ON person(local_uid)");
            } catch (Exception ignored) {}
            try {
                Cursor res = db.rawQuery("select rowid, local_uid from person", null);
                res.moveToFirst();
                while (!res.isAfterLast()) {
                    long rid = res.getLong(0);
                    String lu = null;
                    try { lu = res.getString(1); } catch (Exception ignored) {}
                    if (lu == null || lu.isEmpty()) {
                        ContentValues cv = new ContentValues();
                        cv.put("local_uid", UUID.randomUUID().toString());
                        db.update("person", cv, "rowid = ?", new String[]{String.valueOf(rid)});
                    }
                    res.moveToNext();
                }
                res.close();
            } catch (Exception ignored) {}
        }
        if (oldVersion < 9) {
            try {
                db.execSQL("ALTER TABLE attendance_queue ADD COLUMN local_uid text");
            } catch (Exception ignored) {}
        }
        if (oldVersion < 10) {
            try { db.execSQL("ALTER TABLE person ADD COLUMN phone text"); } catch (Exception ignored) {}
            try { db.execSQL("ALTER TABLE person ADD COLUMN department text"); } catch (Exception ignored) {}
            try { db.execSQL("ALTER TABLE person ADD COLUMN designation text"); } catch (Exception ignored) {}
            try { db.execSQL("ALTER TABLE person ADD COLUMN shift text"); } catch (Exception ignored) {}
            try { db.execSQL("ALTER TABLE person ADD COLUMN custom_data text"); } catch (Exception ignored) {}
            try { db.execSQL("ALTER TABLE person ADD COLUMN synced integer default 1"); } catch (Exception ignored) {}
            try { db.execSQL("ALTER TABLE person ADD COLUMN id text"); } catch (Exception ignored) {}
            try { db.execSQL("ALTER TABLE person ADD COLUMN local_uid text"); } catch (Exception ignored) {}
            try { db.execSQL("CREATE UNIQUE INDEX IF NOT EXISTS idx_person_local_uid ON person(local_uid)"); } catch (Exception ignored) {}
        }
        if (oldVersion < 11) {
            try {
                db.execSQL(
                        "create table if not exists delete_queue " +
                                "(id integer primary key autoincrement, person_id text, local_uid text, name text, created_at text)"
                );
            } catch (Exception ignored) {}
        }
        if (oldVersion < 12) {
            try {
                db.execSQL(
                        "create table if not exists attendance_state " +
                                "(id_key text primary key, person_id text, local_uid text, name text, last_status text, last_timestamp text)"
                );
            } catch (Exception ignored) {}
        }
    }

    private String ensureLocalUid(String localUid) {
        if (localUid != null && !localUid.isEmpty()) return localUid;
        return UUID.randomUUID().toString();
    }

    private void insertPersonInternal(String localUid, String id, String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift, String customData, boolean synced) {

        String existingLocalUid = null;
        boolean exists = false;
        if (id != null && !id.isEmpty()) {
            for (int i = 0; i < personList.size(); i++) {
                Person p = personList.get(i);
                if (p.id != null && p.id.equals(id)) {
                    exists = true;
                    existingLocalUid = p.localUid;
                    personList.remove(i);
                    break;
                }
            }
            if (!exists && templates != null) {
                for (int i = 0; i < personList.size(); i++) {
                    Person p = personList.get(i);
                    if (p.templates != null && Arrays.equals(p.templates, templates)) {
                        exists = true;
                        existingLocalUid = p.localUid;
                        personList.remove(i);
                        break;
                    }
                }
            }
        } else if (localUid != null && !localUid.isEmpty()) {
            for (int i = 0; i < personList.size(); i++) {
                Person p = personList.get(i);
                if (p.localUid != null && p.localUid.equals(localUid)) {
                    exists = true;
                    existingLocalUid = p.localUid;
                    personList.remove(i);
                    break;
                }
            }
        } else if (templates != null) {
            for (int i = 0; i < personList.size(); i++) {
                Person p = personList.get(i);
                if (p.templates != null && Arrays.equals(p.templates, templates)) {
                    exists = true;
                    existingLocalUid = p.localUid;
                    if ((p.id != null && !p.id.isEmpty()) && (id == null || id.isEmpty())) {
                        id = p.id;
                    }
                    personList.remove(i);
                    break;
                }
            }
        }

        if (face == null || face.isRecycled()) {
            return;
        }

        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        face.compress(Bitmap.CompressFormat.PNG, 100, byteArrayOutputStream);
        byte[] faceJpg = byteArrayOutputStream.toByteArray();

        String effectiveLocalUid = ensureLocalUid(existingLocalUid != null ? existingLocalUid : localUid);

        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("local_uid", effectiveLocalUid);
        contentValues.put("id", id);
        contentValues.put("name", name);
        contentValues.put("face", faceJpg);
        contentValues.put("templates", templates);
        contentValues.put("phone", phone);
        contentValues.put("department", department);
        contentValues.put("designation", designation);
        contentValues.put("shift", shift);
        contentValues.put("custom_data", customData);
        contentValues.put("synced", synced ? 1 : 0);

        if (exists) {
            if (id != null && !id.isEmpty()) {
                int updated = db.update("person", contentValues, "id = ?", new String[]{id});
                if (updated == 0) {
                    db.update("person", contentValues, "local_uid = ?", new String[]{effectiveLocalUid});
                }
            } else {
                db.update("person", contentValues, "local_uid = ?", new String[]{effectiveLocalUid});
            }
        } else {
            long res = db.insert("person", null, contentValues);
            if (res == -1) {
                db.update("person", contentValues, "local_uid = ?", new String[]{effectiveLocalUid});
            }
        }

        Person p = new Person(effectiveLocalUid, id, name, templates, phone, department, designation, shift, customData);
        p.synced = synced;
        personList.add(p);
    }

    public void insertPerson (String id, String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift, String customData, boolean synced) {
        insertPersonInternal(null, id, name, face, templates, phone, department, designation, shift, customData, synced);
    }

    public String insertLocalPerson(String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift, String customData) {
        String localUid = ensureLocalUid(null);
        insertPersonInternal(localUid, "", name, face, templates, phone, department, designation, shift, customData, false);
        return localUid;
    }

    public void insertPerson (String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift, boolean synced) {
        insertPersonInternal(null, "", name, face, templates, phone, department, designation, shift, "", synced);
    }

    public void insertPerson (String name, Bitmap face, byte[] templates, String phone, String department, String designation, boolean synced) {
        insertPerson(name, face, templates, phone, department, designation, "", synced);
    }
    
    // Overload for backward compatibility (defaults to synced=true)
    public void insertPerson (String name, Bitmap face, byte[] templates, String phone, String department, String designation) {
        insertPerson(name, face, templates, phone, department, designation, true);
    }

    public void updatePersonStatus(String name, boolean synced) {
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("synced", synced ? 1 : 0);
        db.update("person", contentValues, "name = ?", new String[]{name});
        
        for (Person p : personList) {
            if (p.name.equals(name)) {
                p.synced = synced;
                break;
            }
        }
    }

    public void updatePersonStatusById(String id, boolean synced) {
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("synced", synced ? 1 : 0);
        db.update("person", contentValues, "id = ?", new String[]{id});

        for (Person p : personList) {
            if (p.id != null && p.id.equals(id)) {
                p.synced = synced;
                break;
            }
        }
    }

    public void updatePersonIdByName(String name, String id) {
        if (name == null || name.isEmpty() || id == null || id.isEmpty()) return;
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("id", id);

        db.update("person", contentValues, "name = ? AND (id IS NULL OR id = '')", new String[]{name});

        for (Person p : personList) {
            if (p.name != null && p.name.equals(name) && (p.id == null || p.id.isEmpty())) {
                p.id = id;
                break;
            }
        }
    }

    public void updatePersonAfterSyncByLocalUid(String localUid, String id) {
        if (localUid == null || localUid.isEmpty() || id == null || id.isEmpty()) return;
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("id", id);
        contentValues.put("synced", 1);
        db.update("person", contentValues, "local_uid = ?", new String[]{localUid});

        for (Person p : personList) {
            if (p.localUid != null && p.localUid.equals(localUid)) {
                p.id = id;
                p.synced = true;
                break;
            }
        }
    }

    public void updatePersonStatusByLocalUid(String localUid, boolean synced) {
        if (localUid == null || localUid.isEmpty()) return;
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("synced", synced ? 1 : 0);
        db.update("person", contentValues, "local_uid = ?", new String[]{localUid});

        for (Person p : personList) {
            if (p.localUid != null && p.localUid.equals(localUid)) {
                p.synced = synced;
                break;
            }
        }
    }

    public void updatePerson(String id, String name, String phone, String department, String designation, String shift, String customData) {
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("phone", phone);
        contentValues.put("department", department);
        contentValues.put("designation", designation);
        contentValues.put("shift", shift);
        contentValues.put("custom_data", customData);

        if (id != null && !id.isEmpty()) {
             db.update("person", contentValues, "id = ?", new String[]{id});
        } else {
             db.update("person", contentValues, "name = ?", new String[]{name});
        }

        // Update in-memory list
        for (Person p : personList) {
            if (id != null && !id.isEmpty() && p.id != null && p.id.equals(id)) {
                p.phone = phone;
                p.department = department;
                p.designation = designation;
                p.shift = shift;
                p.customData = customData;
                break;
            } else if (p.name.equals(name)) {
                p.phone = phone;
                p.department = department;
                p.designation = designation;
                p.shift = shift;
                p.customData = customData;
                break;
            }
        }
    }

    public void updatePerson(String name, String phone, String department, String designation) {
        updatePerson("", name, phone, department, designation, "", "");
    }

    public Integer deletePerson (String name) {
        for(int i = 0; i < personList.size(); i ++) {
            if(personList.get(i).name.equals(name)) {
                personList.remove(i);
                i --;
            }
        }

        SQLiteDatabase db = this.getWritableDatabase();
        return db.delete("person",
                "name = ? ",
                new String[] { name });
    }

    public Integer deletePersonById (String id) {
        for(int i = 0; i < personList.size(); i ++) {
            if(personList.get(i).id != null && personList.get(i).id.equals(id)) {
                personList.remove(i);
                i --;
            }
        }

        SQLiteDatabase db = this.getWritableDatabase();
        return db.delete("person",
                "id = ? ",
                new String[] { id });
    }

    public Integer clearDB () {
        personList.clear();

        SQLiteDatabase db = this.getWritableDatabase();
        db.execSQL("delete from person");
        return 0;
    }

    public void loadPerson() {
        personList.clear();

        SQLiteDatabase db = this.getReadableDatabase();
        Cursor res =  db.rawQuery( "select rowid, * from person", null );
        res.moveToFirst();

        while(res.isAfterLast() == false){
            String name = res.getString(res.getColumnIndexOrThrow("name"));
            byte[] templates = null;
            try { templates = res.getBlob(res.getColumnIndexOrThrow("templates")); } catch (Exception ignored) {}
            
            if (templates == null) {
                res.moveToNext();
                continue;
            }
            
            String localUid = "";
            int localUidIdx = res.getColumnIndex("local_uid");
            if (localUidIdx != -1) localUid = res.getString(localUidIdx);
            if (localUid == null || localUid.isEmpty()) {
                try {
                    long rid = res.getLong(res.getColumnIndexOrThrow("rowid"));
                    String newUid = UUID.randomUUID().toString();
                    ContentValues cv = new ContentValues();
                    cv.put("local_uid", newUid);
                    db.update("person", cv, "rowid = ?", new String[]{String.valueOf(rid)});
                    localUid = newUid;
                } catch (Exception ignored) {}
            }

            String id = "";
            int idIdx = res.getColumnIndex("id");
            if (idIdx != -1) id = res.getString(idIdx);
            
            // Handle potentially missing columns if something went wrong with upgrade, though unlikely
            String phone = "";
            String department = "";
            String designation = "";
            
            int phoneIdx = res.getColumnIndex("phone");
            if (phoneIdx != -1) phone = res.getString(phoneIdx);
            
            int deptIdx = res.getColumnIndex("department");
            if (deptIdx != -1) department = res.getString(deptIdx);
            
            int desigIdx = res.getColumnIndex("designation");
            if (desigIdx != -1) designation = res.getString(desigIdx);
            
            String shift = "";
            int shiftIdx = res.getColumnIndex("shift");
            if (shiftIdx != -1) shift = res.getString(shiftIdx);
            
            String customData = "";
            int customDataIdx = res.getColumnIndex("custom_data");
            if (customDataIdx != -1) customData = res.getString(customDataIdx);
            
            boolean synced = true;
            int syncedIdx = res.getColumnIndex("synced");
            if (syncedIdx != -1) synced = res.getInt(syncedIdx) == 1;

            Person person = new Person(localUid, id, name, templates, phone, department, designation, shift, customData);
            person.synced = synced;
            
            // Deduplicate
            boolean found = false;
            for (int i = 0; i < personList.size(); i++) {
                Person p = personList.get(i);
                if (id != null && !id.isEmpty() && p.id != null && p.id.equals(id)) {
                    personList.set(i, person);
                    found = true;
                    break;
                } else if ((id == null || id.isEmpty()) && localUid != null && !localUid.isEmpty() && p.localUid != null && p.localUid.equals(localUid)) {
                    personList.set(i, person);
                    found = true;
                    break;
                } else if (templates != null && p.templates != null && Arrays.equals(p.templates, templates)) {
                    boolean keepNew = (id != null && !id.isEmpty()) && (p.id == null || p.id.isEmpty());
                    if (keepNew) {
                        personList.set(i, person);
                    }
                    found = true;
                    break;
                }
            }
            if (!found) {
                personList.add(person);
            }

            res.moveToNext();
        }
        res.close();
    }

    public boolean personExists(String name) {
        for (Person p : personList) {
            if (p.name.equals(name)) return true;
        }
        return false;
    }

    // --- Offline Attendance Queue Methods ---

    public void insertAttendanceQueue(String personId, String name, String timestamp, String status, Bitmap image, boolean isLate) {
        insertAttendanceQueue(personId, null, name, timestamp, status, image, isLate);
    }

    public void insertAttendanceQueue(String personId, String localUid, String name, String timestamp, String status, Bitmap image, boolean isLate) {
        SQLiteDatabase db = this.getWritableDatabase();
        String effectivePersonId = personId;
        if ((effectivePersonId == null || effectivePersonId.isEmpty()) && localUid != null && !localUid.isEmpty()) {
            effectivePersonId = resolvePersonId(localUid);
        }
        ContentValues contentValues = new ContentValues();
        contentValues.put("person_id", effectivePersonId);
        contentValues.put("local_uid", localUid);
        contentValues.put("name", name);
        contentValues.put("timestamp", timestamp);
        contentValues.put("status", status);
        contentValues.put("is_late", isLate ? 1 : 0);

        if (image != null) {
            ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
            image.compress(Bitmap.CompressFormat.JPEG, 60, byteArrayOutputStream);
            contentValues.put("image", byteArrayOutputStream.toByteArray());
        }

        db.insert("attendance_queue", null, contentValues);
        upsertAttendanceState(effectivePersonId, localUid, name, status, timestamp);
    }

    public String predictNextAttendanceStatus(String personId, String localUid) {
        return predictNextAttendanceStatus(personId, localUid, null);
    }

    public String predictNextAttendanceStatus(String personId, String localUid, String name) {
        String last = getLastAttendanceStatus(personId, localUid, name);
        if ("CHECK_IN".equalsIgnoreCase(last)) return "CHECK_OUT";
        return "CHECK_IN";
    }

    public String getLastAttendanceStatus(String personId, String localUid, String name) {
        String fromState = getAttendanceStateStatus(personId, localUid, name);
        if (fromState != null && !fromState.isEmpty()) return fromState;
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor c = null;
        try {
            String sql;
            String[] args;
            if (personId != null && !personId.isEmpty()) {
                sql = "select status from attendance_queue where person_id = ? and status is not null and trim(status) != '' order by timestamp desc, id desc limit 1";
                args = new String[]{personId};
            } else if (localUid != null && !localUid.isEmpty()) {
                sql = "select status from attendance_queue where local_uid = ? and status is not null and trim(status) != '' order by timestamp desc, id desc limit 1";
                args = new String[]{localUid};
            } else {
                return null;
            }
            c = db.rawQuery(sql, args);
            if (c.moveToFirst()) {
                String s = c.getString(0);
                return normalizeAttendanceStatus(s);
            }
        } catch (Exception ignored) {
        } finally {
            if (c != null) {
                try { c.close(); } catch (Exception ignored) {}
            }
        }
        return null;
    }

    public String getLastAttendanceTimestamp(String personId, String localUid, String name) {
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor c = null;
        try {
            String key = makeAttendanceStateKey(personId, localUid, name);
            if (key == null) return null;
            c = db.rawQuery("select last_timestamp from attendance_state where id_key = ? limit 1", new String[]{key});
            if (c.moveToFirst()) {
                return c.getString(0);
            }
        } catch (Exception ignored) {
        } finally {
            if (c != null) {
                try { c.close(); } catch (Exception ignored) {}
            }
        }
        return null;
    }

    public void upsertAttendanceState(String personId, String localUid, String name, String status, String timestamp) {
        SQLiteDatabase db = this.getWritableDatabase();
        String key = makeAttendanceStateKey(personId, localUid, name);
        if (key == null) return;
        ContentValues cv = new ContentValues();
        cv.put("id_key", key);
        cv.put("person_id", personId);
        cv.put("local_uid", localUid);
        cv.put("name", name);
        cv.put("last_status", normalizeAttendanceStatus(status));
        cv.put("last_timestamp", timestamp);
        db.insertWithOnConflict("attendance_state", null, cv, SQLiteDatabase.CONFLICT_REPLACE);
    }

    public String getAttendanceStateStatus(String personId, String localUid, String name) {
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor c = null;
        try {
            String key = makeAttendanceStateKey(personId, localUid, name);
            if (key == null) return null;
            c = db.rawQuery("select last_status from attendance_state where id_key = ? limit 1", new String[]{key});
            if (c.moveToFirst()) {
                return normalizeAttendanceStatus(c.getString(0));
            }
        } catch (Exception ignored) {
        } finally {
            if (c != null) {
                try { c.close(); } catch (Exception ignored) {}
            }
        }
        return null;
    }

    private String makeAttendanceStateKey(String personId, String localUid, String name) {
        if (personId != null && !personId.isEmpty()) return "pid:" + personId;
        if (localUid != null && !localUid.isEmpty()) return "lu:" + localUid;
        return null;
    }

    private String normalizeAttendanceStatus(String status) {
        if (status == null) return null;
        String cleaned = status.trim();
        if (cleaned.isEmpty()) return null;
        if ("pending".equalsIgnoreCase(cleaned)) return "CHECK_IN";
        return cleaned.toUpperCase();
    }

    public ArrayList<QueueItem> getAttendanceQueue() {
        ArrayList<QueueItem> list = new ArrayList<>();
        SQLiteDatabase db = this.getReadableDatabase();
        try {
            Cursor res = db.rawQuery("select * from attendance_queue", null);
            res.moveToFirst();

            while (!res.isAfterLast()) {
                QueueItem item = new QueueItem();
                item.id = res.getInt(res.getColumnIndexOrThrow("id"));
                
                int pIdIdx = res.getColumnIndex("person_id");
                if (pIdIdx != -1) item.personId = res.getString(pIdIdx);

                int luIdx = res.getColumnIndex("local_uid");
                if (luIdx != -1) item.localUid = res.getString(luIdx);
                
                item.name = res.getString(res.getColumnIndexOrThrow("name"));
                item.timestamp = res.getString(res.getColumnIndexOrThrow("timestamp"));
                item.status = res.getString(res.getColumnIndexOrThrow("status"));
                item.isLate = res.getInt(res.getColumnIndexOrThrow("is_late")) == 1;
                
                byte[] img = res.getBlob(res.getColumnIndexOrThrow("image"));
                if (img != null) {
                    item.image = android.util.Base64.encodeToString(img, android.util.Base64.NO_WRAP);
                }
                
                list.add(item);
                res.moveToNext();
            }
            res.close();
        } catch (Exception e) {
            e.printStackTrace();
        }
        return list;
    }

    public void deleteQueueItem(int id) {
        SQLiteDatabase db = this.getWritableDatabase();
        db.delete("attendance_queue", "id = ?", new String[]{String.valueOf(id)});
    }

    public static class QueueItem {
        public int id;
        public String personId;
        public String localUid;
        public String name;
        public String timestamp;
        public String status;
        public boolean isLate;
        public String image; // Base64
    }

    public String resolvePersonId(String localUid, String name) {
        return resolvePersonId(localUid);
    }

    public String resolvePersonId(String localUid) {
        try {
            SQLiteDatabase db = this.getReadableDatabase();
            if (localUid != null && !localUid.isEmpty()) {
                Cursor c = db.rawQuery("select id from person where local_uid = ? limit 1", new String[]{localUid});
                try {
                    if (c.moveToFirst()) {
                        String id = c.getString(0);
                        if (id != null && !id.isEmpty()) return id;
                    }
                } finally {
                    c.close();
                }
            }
        } catch (Exception ignored) {}
        return null;
    }

    public ArrayList<Person> getUnsyncedPersons() {
        ArrayList<Person> list = new ArrayList<>();
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor res = null;
        try {
            res = db.rawQuery("select local_uid, id, name, face, templates, phone, department, designation, shift, custom_data, synced from person where synced = 0", null);
            if (res.moveToFirst()) {
                while (!res.isAfterLast()) {
                    String localUid = res.getString(res.getColumnIndexOrThrow("local_uid"));
                    String id = "";
                    int idIdx = res.getColumnIndex("id");
                    if (idIdx != -1) id = res.getString(idIdx);
                    String name = res.getString(res.getColumnIndexOrThrow("name"));
                    byte[] faceJpg = res.getBlob(res.getColumnIndexOrThrow("face"));
                    byte[] templates = res.getBlob(res.getColumnIndexOrThrow("templates"));
                    String phone = "";
                    String department = "";
                    String designation = "";
                    String shift = "";
                    String customData = "";
                    int phoneIdx = res.getColumnIndex("phone");
                    if (phoneIdx != -1) phone = res.getString(phoneIdx);
                    int deptIdx = res.getColumnIndex("department");
                    if (deptIdx != -1) department = res.getString(deptIdx);
                    int desigIdx = res.getColumnIndex("designation");
                    if (desigIdx != -1) designation = res.getString(desigIdx);
                    int shiftIdx = res.getColumnIndex("shift");
                    if (shiftIdx != -1) shift = res.getString(shiftIdx);
                    int cdIdx = res.getColumnIndex("custom_data");
                    if (cdIdx != -1) customData = res.getString(cdIdx);

                    if (templates != null) {
                        Person p = new Person(localUid, id, name, templates, phone, department, designation, shift, customData);
                        p.synced = false;
                        list.add(p);
                    }
                    res.moveToNext();
                }
            }
        } catch (Exception ignored) {
        } finally {
            try {
                if (res != null) res.close();
            } catch (Exception ignored) {}
        }
        return list;
    }

    public void insertDeleteQueue(String personId, String localUid, String name, String createdAt) {
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues cv = new ContentValues();
        cv.put("person_id", personId);
        cv.put("local_uid", localUid);
        cv.put("name", name);
        cv.put("created_at", createdAt);
        db.insert("delete_queue", null, cv);
    }

    public ArrayList<DeleteQueueItem> getDeleteQueue() {
        ArrayList<DeleteQueueItem> list = new ArrayList<>();
        SQLiteDatabase db = this.getReadableDatabase();
        Cursor res = null;
        try {
            res = db.rawQuery("select * from delete_queue", null);
            if (res.moveToFirst()) {
                while (!res.isAfterLast()) {
                    DeleteQueueItem item = new DeleteQueueItem();
                    item.id = res.getInt(res.getColumnIndexOrThrow("id"));
                    int pidIdx = res.getColumnIndex("person_id");
                    if (pidIdx != -1) item.personId = res.getString(pidIdx);
                    int luIdx = res.getColumnIndex("local_uid");
                    if (luIdx != -1) item.localUid = res.getString(luIdx);
                    int nameIdx = res.getColumnIndex("name");
                    if (nameIdx != -1) item.name = res.getString(nameIdx);
                    int caIdx = res.getColumnIndex("created_at");
                    if (caIdx != -1) item.createdAt = res.getString(caIdx);
                    list.add(item);
                    res.moveToNext();
                }
            }
        } catch (Exception ignored) {
        } finally {
            try {
                if (res != null) res.close();
            } catch (Exception ignored) {}
        }
        return list;
    }

    public void deleteDeleteQueueItem(int id) {
        SQLiteDatabase db = this.getWritableDatabase();
        db.delete("delete_queue", "id = ?", new String[]{String.valueOf(id)});
    }

    public static class DeleteQueueItem {
        public int id;
        public String personId;
        public String localUid;
        public String name;
        public String createdAt;
    }
}
