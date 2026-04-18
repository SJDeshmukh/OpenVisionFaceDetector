package com.faceplugin.facerecognition;

import android.app.AlertDialog;
import android.content.DialogInterface;
import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Toast;
import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

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
        
        dbManager = new DBManager(requireContext().getApplicationContext());
        dbManager.loadPerson(); // Ensure latest data is loaded

        recyclerView = view.findViewById(R.id.recycler_users);
        recyclerView.setLayoutManager(new GridLayoutManager(getContext(), 2));
        
        if (DBManager.personList != null) {
             adapter = new UserAdapter(DBManager.personList, dbManager);
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
        boolean hasId = person.id != null && !person.id.isEmpty();
        if (hasId) {
            dbManager.deletePersonById(person.id);
        } else {
            dbManager.deletePerson(person.name);
        }
        
        // 2. Update UI
        adapter.notifyItemRemoved(position);
        adapter.notifyItemRangeChanged(position, adapter.getItemCount());
        Toast.makeText(getContext(), "Deleted locally", Toast.LENGTH_SHORT).show();

        if (person != null && !person.synced) {
            return;
        }

        boolean online = false;
        try {
            online = NetworkUtils.INSTANCE.isOnline(requireContext().getApplicationContext());
        } catch (Exception ignored) {}

        // 3. Delete from Backend (or queue if offline)
        if (!online) {
            queueDelete(person);
            try {
                SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
            } catch (Exception ignored) {}
            return;
        }

        GreetingService service = RetrofitClient.getService();
        Call<Void> call = hasId ? service.deleteFaceById(person.id) : service.deleteFace(person.name);
        call.enqueue(new Callback<Void>() {
            @Override
            public void onResponse(Call<Void> call, Response<Void> response) {
                if (response.isSuccessful()) {
                    if (getActivity() != null) {
                         Toast.makeText(getContext(), "Deleted from backend", Toast.LENGTH_SHORT).show();
                    }
                } else {
                    queueDelete(person);
                    try {
                        SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                    } catch (Exception ignored) {}
                }
            }

            @Override
            public void onFailure(Call<Void> call, Throwable t) {
                queueDelete(person);
                try {
                    SyncScheduler.scheduleImmediate(requireContext().getApplicationContext());
                } catch (Exception ignored) {}
            }
        });
    }

    private void queueDelete(Person person) {
        try {
            String pid = (person != null && person.id != null) ? person.id : null;
            String localUid = (person != null && person.localUid != null) ? person.localUid : null;
            String name = (person != null && person.name != null) ? person.name : null;
            String ts = new SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS", Locale.US).format(new Date());
            dbManager.insertDeleteQueue(pid, localUid, name, ts);
        } catch (Exception ignored) {}
    }
    
    @Override
    public void onResume() {
        super.onResume();
        if (!isHidden()) {
            refreshList();
        }
    }

    @Override
    public void onHiddenChanged(boolean hidden) {
        super.onHiddenChanged(hidden);
        if (!hidden) {
            refreshList();
        }
    }

    public void refreshList() {
        try {
            if (dbManager != null) {
                dbManager.loadPerson();
            }
        } catch (Exception ignored) {}
        if (adapter != null) adapter.notifyDataSetChanged();
    }
}
