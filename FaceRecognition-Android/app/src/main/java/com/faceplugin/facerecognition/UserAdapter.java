package com.faceplugin.facerecognition;

import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.TextView;
import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;
import java.util.List;

public class UserAdapter extends RecyclerView.Adapter<UserAdapter.UserViewHolder> {

    private List<Person> userList;
    private OnUserDeleteListener deleteListener;
    private DBManager dbManager;

    public interface OnUserDeleteListener {
        void onDeleteUser(Person person, int position);
    }

    public void setOnUserDeleteListener(OnUserDeleteListener listener) {
        this.deleteListener = listener;
    }

    public UserAdapter(List<Person> userList, DBManager dbManager) {
        this.userList = userList;
        this.dbManager = dbManager;
    }

    @NonNull
    @Override
    public UserViewHolder onCreateViewHolder(@NonNull ViewGroup parent, int viewType) {
        View view = LayoutInflater.from(parent.getContext()).inflate(R.layout.item_user_card, parent, false);
        return new UserViewHolder(view);
    }

    @Override
    public void onBindViewHolder(@NonNull UserViewHolder holder, int position) {
        Person person = userList.get(position);
        holder.tvName.setText(person.name);
        
        if (person.face != null) {
            holder.imgFace.setImageBitmap(person.face);
        } else if (dbManager != null && person.localUid != null) {
            // Lazy load from DB if not in memory
            android.graphics.Bitmap face = dbManager.getPersonFace(person.localUid);
            if (face != null) {
                person.face = face; // Cache in memory once loaded
                holder.imgFace.setImageBitmap(face);
            } else {
                holder.imgFace.setImageResource(R.drawable.openvision_logo);
            }
        } else {
            holder.imgFace.setImageResource(R.drawable.openvision_logo);
        }
        
        String details = "";
        if (person.department != null && !person.department.isEmpty()) {
            details += person.department;
        }
        if (person.designation != null && !person.designation.isEmpty()) {
            if (!details.isEmpty()) details += " • ";
            details += person.designation;
        }
        if (details.isEmpty()) {
             details = "ID: " + (position + 1);
        }
        holder.tvDetails.setText(details);

        holder.itemView.setOnLongClickListener(v -> {
            if (deleteListener != null) {
                deleteListener.onDeleteUser(person, holder.getAdapterPosition());
            }
            return true;
        });
    }

    @Override
    public int getItemCount() {
        return userList.size();
    }

    static class UserViewHolder extends RecyclerView.ViewHolder {
        ImageView imgFace;
        TextView tvName, tvDetails;

        public UserViewHolder(@NonNull View itemView) {
            super(itemView);
            imgFace = itemView.findViewById(R.id.img_face);
            tvName = itemView.findViewById(R.id.tv_name);
            tvDetails = itemView.findViewById(R.id.tv_details);
        }
    }
}