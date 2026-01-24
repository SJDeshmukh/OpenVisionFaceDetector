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
        super(context, "mydb" , null, 2);
    }

    @Override
    public void onCreate(SQLiteDatabase db) {
        // TODO Auto-generated method stub
        db.execSQL(
                "create table person " +
                        "(name text, face blob, templates blob, phone text, department text, designation text)"
        );
    }

    @Override
    public void onUpgrade(SQLiteDatabase db, int oldVersion, int newVersion) {
        // TODO Auto-generated method stub
        db.execSQL("DROP TABLE IF EXISTS person");
        onCreate(db);
    }

    public void insertPerson (String name, Bitmap face, byte[] templates, String phone, String department, String designation) {

        ByteArrayOutputStream byteArrayOutputStream = new ByteArrayOutputStream();
        face.compress(Bitmap.CompressFormat.PNG, 100, byteArrayOutputStream);
        byte[] faceJpg = byteArrayOutputStream.toByteArray();

        SQLiteDatabase db = this.getWritableDatabase();
        ContentValues contentValues = new ContentValues();
        contentValues.put("name", name);
        contentValues.put("face", faceJpg);
        contentValues.put("templates", templates);
        contentValues.put("phone", phone);
        contentValues.put("department", department);
        contentValues.put("designation", designation);
        db.insert("person", null, contentValues);

        personList.add(new Person(name, face, templates, phone, department, designation));
    }

    public Integer deletePerson (String name) {
        for(int i = 0; i < personList.size(); i ++) {
            if(personList.get(i).name == name) {
                personList.remove(i);
                i --;
            }
        }

        SQLiteDatabase db = this.getWritableDatabase();
        return db.delete("person",
                "name = ? ",
                new String[] { name });
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

            Bitmap face = BitmapFactory.decodeByteArray(faceJpg, 0, faceJpg.length);

            Person person = new Person(name, face, templates, phone, department, designation);
            personList.add(person);

            res.moveToNext();
        }
        res.close();
    }
}