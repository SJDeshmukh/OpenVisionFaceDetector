package com.faceplugin.facerecognition

import android.os.Bundle
import androidx.appcompat.app.AppCompatActivity
import androidx.fragment.app.Fragment
import com.google.android.material.bottomnavigation.BottomNavigationView

class OwnerActivity : AppCompatActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_owner)

        val bottomNavigation = findViewById<BottomNavigationView>(R.id.owner_bottom_navigation)
        
        bottomNavigation.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.owner_nav_advances -> {
                    loadFragment(OwnerAdvanceFragment())
                    true
                }
                R.id.owner_nav_insights -> {
                    loadFragment(OwnerInsightsFragment())
                    true
                }
                else -> false
            }
        }

        // Default fragment
        if (savedInstanceState == null) {
            bottomNavigation.selectedItemId = R.id.owner_nav_advances
        }
    }

    private fun loadFragment(fragment: Fragment) {
        supportFragmentManager.beginTransaction()
            .replace(R.id.owner_fragment_container, fragment)
            .commit()
    }
}
