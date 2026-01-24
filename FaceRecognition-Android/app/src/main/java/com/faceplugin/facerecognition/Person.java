package com.faceplugin.facerecognition;

import android.graphics.Bitmap;

public class Person {

    public String name;
    public Bitmap face;
    public byte[] templates;
    public String phone;
    public String department;
    public String designation;

    public Person() {

    }

    public Person(String name, Bitmap face, byte[] templates, String phone, String department, String designation) {
        this.name = name;
        this.face = face;
        this.templates = templates;
        this.phone = phone;
        this.department = department;
        this.designation = designation;
    }

    // Constructor for backward compatibility if needed, though we should migrate all usages
    public Person(String name, Bitmap face, byte[] templates) {
        this(name, face, templates, "", "", "");
    }
}
