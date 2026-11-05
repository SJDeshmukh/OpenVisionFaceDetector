package com.faceplugin.facerecognition;

import static org.junit.Assert.assertEquals;

import org.junit.Test;

public class RegistrationFieldKeyTest {
    @Test
    public void acceptsSuperAdminFieldNamingStyles() {
        assertEquals("name", EnrollFragment.canonicalFieldKey("EmployeeName"));
        assertEquals("name", EnrollFragment.canonicalFieldKey("employeeName"));
        assertEquals("name", EnrollFragment.canonicalFieldKey("employee_name"));
        assertEquals("phone", EnrollFragment.canonicalFieldKey("PhoneNumber"));
        assertEquals("shift", EnrollFragment.canonicalFieldKey("WorkShift"));
        assertEquals("employee_code", EnrollFragment.canonicalFieldKey("EmployeeCode"));
    }
}
