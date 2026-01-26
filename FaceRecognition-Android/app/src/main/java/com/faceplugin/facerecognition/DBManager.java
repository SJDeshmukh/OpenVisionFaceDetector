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

public class DBManager extends SQLiteOpenHelper {

    public static ArrayList<Person> personList = new ArrayList<Person>();

    public DBManager(Context context) {
        super(context, "mydb" , null, 6);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        // TODO Auto-generated method stub
        db.execSQL(
                "create table person " +
                        "(id text, name text, face blob, templates blob, phone text, department text, designation text, shift text, synced integer default 1)"
        );
        db.execSQL(
                "create table attendance_queue " +
                        "(id integer primary key autoincrement, person_id text, name text, timestamp text, status text, image blob, is_late integer)"
        );
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // TODO Auto-generated method stub
        db.execSQL("DROP TABLE IF EXISTS person");
        db.execSQL("DROP TABLE IF EXISTS attendance_queue");
        onCreate(db);
    }

    public void insertPerson (String id, String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift, boolean synced) {

        String existingId = null;
        // Check if person already exists
        boolean exists = false;
        for (int i = 0; i < personList.size(); i++) {
            Person p = personList.get(i);
            if (id != null && !id.isEmpty() && p.id != null && p.id.equals(id)) {
                exists = true;
                existingId = p.id;
                personList.remove(i);
                break;
            } else if (p.name.equals(name)) {
                // Only merge if local ID is missing OR incoming ID is missing
                // If both have IDs and they differ, do not merge (it's a name collision, which is allowed now)
                if ((p.id == null || p.id.isEmpty()) || (id == null || id.isEmpty())) {
                    exists = true;
                    existingId = p.id;
                    personList.remove(i);
                    break;
                }
            }
        }

        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        face.compress(Bitmap.CompressFormat.PNG, 100, byteArrayOutputStream);
        byte[] faceJpg = byteArrayOutputStream.toByteArray();

        // Preserve existing ID if incoming ID is missing
        if ((id == null || id.isEmpty()) && (existingId != null && !existingId.isEmpty())) {
            id = existingId;
        }

        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("id", id);
        contentValues.put("name", name);
        contentValues.put("face", faceJpg);
        contentValues.put("templates", templates);
        contentValues.put("phone", phone);
        contentValues.put("department", department);
        contentValues.put("designation", designation);
        contentValues.put("shift", shift);
        contentValues.put("synced", synced ? 1 : 0);

        if (exists) {
            if (id != null && !id.isEmpty()) {
                db.update("person", contentValues, "id = ?", new String[]{id});
            } else {
                db.update("person", contentValues, "name = ?", new String[]{name});
            }
        } else {
            db.insert("person", null, contentValues);
        }

        Person p = new Person(id, name, face, templates, phone, department, designation, shift);
        p.synced = synced;
        personList.add(p);
    }

    public void insertPerson (String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift, boolean synced) {
        insertPerson("", name, face, templates, phone, department, designation, shift, synced);
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

    public void updatePerson(String name, String phone, String department, String designation) {
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("phone", phone);
        contentValues.put("department", department);
        contentValues.put("designation", designation);

        db.update("person", contentValues, "name = ?", new String[]{name});

        // Update in-memory list
        for (Person p : personList) {
            if (p.name.equals(name)) {
                p.phone = phone;
                p.department = department;
                p.designation = designation;
                break;
            }
        }
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
        Cursor res =  db.rawQuery( "select * from person", null );
        res.moveToFirst();

        while(res.isAfterLast() == false){
            String name = res.getString(res.getColumnIndexOrThrow("name"));
            byte[] faceJpg = res.getBlob(res.getColumnIndexOrThrow("face"));
            byte[] templates = res.getBlob(res.getColumnIndexOrThrow("templates"));
            
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
            
            boolean synced = true;
            int syncedIdx = res.getColumnIndex("synced");
            if (syncedIdx != -1) synced = res.getInt(syncedIdx) == 1;

            Bitmap face = BitmapFactory.decodeByteArray(faceJpg, 0, faceJpg.length);

            Person person = new Person(id, name, face, templates, phone, department, designation, shift);
            person.synced = synced;
            
            // Deduplicate
            boolean found = false;
            for (int i = 0; i < personList.size(); i++) {
                Person p = personList.get(i);
                if (id != null && !id.isEmpty() && p.id != null && p.id.equals(id)) {
                    personList.set(i, person);
                    found = true;
                    break;
                } else if ((id == null || id.isEmpty()) && p.name.equals(name)) {
                    personList.set(i, person);
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
        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("person_id", personId);
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
        public String name;
        public String timestamp;
        public String status;
        public boolean isLate;
        public String image; // Base64
    }
}