package com.faceplugin.facerecognition;

import android.graphics.Bitmap;

public class Person {

    public String localUid;
    public String id; // Backend ID
    public String name;
    public byte[] templates;
    public String phone;
    public String department;
    public String designation;
    public String shift;
    public String customData;
    public Bitmap face;
    public boolean synced = true;

    public Person() {

    }

    public Person(String localUid, String id, String name, byte[] templates, String phone, String department, String designation, String shift, String customData, Bitmap face) {
        this.localUid = localUid;
        this.id = id;
        this.name = name;
        this.templates = templates;
        this.phone = phone;
        this.department = department;
        this.designation = designation;
        this.shift = shift;
        this.customData = customData;
        this.face = face;
    }

    public Person(String localUid, String id, String name, byte[] templates, String phone, String department, String designation, String shift, String customData) {
        this(localUid, id, name, templates, phone, department, designation, shift, customData, null);
    }

    public Person(String id, String name, byte[] templates, String phone, String department, String designation, String shift, String customData) {
        this(null, id, name, templates, phone, department, designation, shift, customData);
    }

    public Person(String id, String name, byte[] templates, String phone, String department, String designation, String shift) {
        this(id, name, templates, phone, department, designation, shift, "");
    }

    // Backward compatibility constructors
    public Person(String name, byte[] templates, String phone, String department, String designation, String shift) {
        this("", name, templates, phone, department, designation, shift);
    }

    // Constructor for backward compatibility if needed, though we should migrate all usages
    public Person(String name, byte[] templates, String phone, String department, String designation) {
        this(name, templates, phone, department, designation, "");
    }

    public Person(String name, byte[] templates) {
        this(name, templates, "", "", "", "");
    }
}
