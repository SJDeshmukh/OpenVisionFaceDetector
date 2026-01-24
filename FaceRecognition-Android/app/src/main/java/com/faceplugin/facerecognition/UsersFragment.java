package com.faceplugin.facerecognition;

import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;
import androidx.recyclerview.widget.GridLayoutManager;
import androidx.recyclerview.widget.RecyclerView;

import com.faceplugin.facerecognition.api.GreetingService;
import com.faceplugin.facerecognition.api.RetrofitClient;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

public class UsersFragment extends Fragment {

    private RecyclerView recyclerView;
    private UserAdapter adapter;
    private DBManager dbManager;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container, @Nullable Bundle savedInstanceState) {
        View view = inflater.inflate(R.layout.fragment_users, container, false);
        
        dbManager = new DBManager(getContext());
        dbManager.loadPerson(); // Ensure latest data is loaded

        recyclerView = view.findViewById(R.id.recycler_users);
        recyclerView.setLayoutManager(new GridLayoutManager(getContext(), 2));
        
        if (DBManager.personList != null) {
             adapter = new UserAdapter(DBManager.personList);
             adapter.setOnUserDeleteListener(new UserAdapter.OnUserDeleteListener() {
                 @Override
                 public void onDeleteUser(Person person, int position) {
                     showDeleteConfirmationDialog(person, position);
                 }
             });
             recyclerView.setAdapter(adapter);
        }

        return view;
    }

    private void showDeleteConfirmationDialog(Person person, int position) {
        new AlertDialog.Builder(getContext())
                .setTitle("Delete User")
                .setMessage("Are you sure you want to delete " + person.name + "?")
                .setPositiveButton("Delete", new DialogInterface.OnClickListener() {
                    public void onClick(DialogInterface dialog, int which) {
                        deleteUser(person, position);
                    }
                })
                .setNegativeButton("Cancel", null)
                .show();
    }

    private void deleteUser(Person person, int position) {
        // 1. Delete from Local DB
        dbManager.deletePerson(person.name);
        
        // 2. Update UI
        adapter.notifyItemRemoved(position);
        adapter.notifyItemRangeChanged(position, adapter.getItemCount());
        Toast.makeText(getContext(), "Deleted locally", Toast.LENGTH_SHORT).show();

        // 3. Delete from Backend
        GreetingService service = RetrofitClient.getService();
        service.deleteFace(person.name).enqueue(new Callback<Void>() {
            @Override
            public void onResponse(Call<Void> call, Response<Void> response) {
                if (response.isSuccessful()) {
                    if (getActivity() != null) {
                         Toast.makeText(getContext(), "Deleted from backend", Toast.LENGTH_SHORT).show();
                    }
                } else {
                    if (getActivity() != null) {
                        Toast.makeText(getContext(), "Failed to delete from backend", Toast.LENGTH_SHORT).show();
                    }
                }
            }

            @Override
            public void onFailure(Call<Void> call, Throwable t) {
                if (getActivity() != null) {
                    Toast.makeText(getContext(), "Error deleting from backend: " + t.getMessage(), Toast.LENGTH_SHORT).show();
                }
            }
        });
    }
    
    @Override
    public void onResume() {
        super.onResume();
        if (adapter != null) {
            adapter.notifyDataSetChanged();
        }
    }
}