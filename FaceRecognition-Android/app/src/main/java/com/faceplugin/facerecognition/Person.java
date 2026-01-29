package com.faceplugin.facerecognition;

import android.graphics.Bitmap;

public class Person {

    public String id; // Backend ID
    public String name;
    public Bitmap face;
    public byte[] templates;
    public String phone;
    public String department;
    public String designation;
    public String shift;
    public String customData;
    public boolean synced = true;

    public Person() {

    }

    public Person(String id, String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift, String customData) {
        this.id = id;
        this.name = name;
        this.face = face;
        this.templates = templates;
        this.phone = phone;
        this.department = department;
        this.designation = designation;
        this.shift = shift;
        this.customData = customData;
    }

    public Person(String id, String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift) {
        this(id, name, face, templates, phone, department, designation, shift, "");
    }

    // Backward compatibility constructors
    public Person(String name, Bitmap face, byte[] templates, String phone, String department, String designation, String shift) {
        this("", name, face, templates, phone, department, designation, shift);
    }

    // Constructor for backward compatibility if needed, though we should migrate all usages
    public Person(String name, Bitmap face, byte[] templates, String phone, String department, String designation) {
        this(name, face, templates, phone, department, designation, "");
    }

    public Person(String name, Bitmap face, byte[] templates) {
        this(name, face, templates, "", "", "", "");
    }
}
