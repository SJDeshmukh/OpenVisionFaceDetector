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
    private android.util.LruCache<String, android.graphics.Bitmap> faceCache;

    public interface OnUserDeleteListener {
        void onDeleteUser(Person person, int position);
    }

    public interface OnUserClickListener {
        void onClickUser(Person person, int position);
    }

    private OnUserClickListener clickListener;

    public void setOnUserDeleteListener(OnUserDeleteListener listener) {
        this.deleteListener = listener;
    }

    public void setOnUserClickListener(OnUserClickListener listener) {
        this.clickListener = listener;
    }

    public UserAdapter(List<Person> userList, DBManager dbManager) {
        this.userList = userList;
        this.dbManager = dbManager;
        // Optimization: 4MB cache for user face thumbnails (enough for ~80-100 thumbnails)
        this.faceCache = new android.util.LruCache<>(4 * 1024 * 1024); 
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
        
        android.graphics.Bitmap cachedFace = faceCache.get(person.localUid != null ? person.localUid : "null");
        if (cachedFace != null) {
            holder.imgFace.setImageBitmap(cachedFace);
        } else if (dbManager != null && person.localUid != null) {
            // Lazy load from DB if not in cache
            android.graphics.Bitmap face = dbManager.getPersonFace(person.localUid);
            if (face != null) {
                faceCache.put(person.localUid, face);
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

        holder.itemView.setOnClickListener(v -> {
            if (clickListener != null) {
                clickListener.onClickUser(person, holder.getAdapterPosition());
            }
        });

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