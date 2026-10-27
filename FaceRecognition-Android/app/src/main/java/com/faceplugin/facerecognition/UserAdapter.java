package com.faceplugin.facerecognition;

import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.util.LruCache;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageView;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.recyclerview.widget.RecyclerView;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

import com.faceplugin.facerecognition.api.RetrofitClient;

public class UserAdapter extends RecyclerView.Adapter<UserAdapter.UserViewHolder> {

    // RecyclerView must never observe DBManager.personList while a sync thread is
    // replacing it. Keep an adapter-owned snapshot instead.
    private final List<Person> userList = new ArrayList<>();
    private final DBManager dbManager;
    private final LruCache<String, Bitmap> faceCache;
    private final ExecutorService imageLoader = Executors.newFixedThreadPool(2);
    private final Set<String> imageLoadsInFlight = ConcurrentHashMap.newKeySet();
    private volatile boolean released = false;
    private OnUserDeleteListener deleteListener;
    private OnUserClickListener clickListener;

    public interface OnUserDeleteListener {
        void onDeleteUser(Person person, int position);
    }

    public interface OnUserClickListener {
        void onClickUser(Person person, int position);
    }

    public UserAdapter(List<Person> users, DBManager dbManager) {
        this.dbManager = dbManager;
        int maxMemoryKb = (int) Math.min(Integer.MAX_VALUE, Runtime.getRuntime().maxMemory() / 1024L);
        int cacheKb = Math.max(4 * 1024, Math.min(16 * 1024, maxMemoryKb / 16));
        this.faceCache = new LruCache<String, Bitmap>(cacheKb) {
            @Override
            protected int sizeOf(@NonNull String key, @NonNull Bitmap bitmap) {
                return Math.max(1, bitmap.getAllocationByteCount() / 1024);
            }
        };
        replaceUsers(users);
    }

    public void setOnUserDeleteListener(OnUserDeleteListener listener) {
        this.deleteListener = listener;
    }

    public void setOnUserClickListener(OnUserClickListener listener) {
        this.clickListener = listener;
    }

    public void replaceUsers(List<Person> users) {
        List<Person> snapshot;
        if (users == null) {
            snapshot = new ArrayList<>();
        } else {
            synchronized (users) {
                snapshot = new ArrayList<>(users);
            }
        }
        userList.clear();
        userList.addAll(snapshot);
        notifyDataSetChanged();
    }

    public void removeUser(Person person) {
        if (person == null) return;
        for (int i = 0; i < userList.size(); i++) {
            if (samePerson(userList.get(i), person)) {
                userList.remove(i);
                notifyItemRemoved(i);
                return;
            }
        }
    }

    public void invalidateFace(Person person) {
        if (person == null) return;
        faceCache.remove(cacheKey(person));
        int index = indexOf(person);
        if (index >= 0) notifyItemChanged(index);
    }

    public void release() {
        released = true;
        imageLoader.shutdownNow();
        faceCache.evictAll();
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
        holder.tvName.setText(person.name == null ? "" : person.name);

        String key = cacheKey(person);
        holder.imgFace.setTag(key);
        Bitmap cachedFace = faceCache.get(key);
        if (cachedFace != null && !cachedFace.isRecycled()) {
            holder.imgFace.setImageBitmap(cachedFace);
        } else {
            holder.imgFace.setImageResource(R.drawable.openvision_logo);
            if (dbManager != null && person.localUid != null && !person.localUid.isEmpty() &&
                    !released && imageLoadsInFlight.add(key)) {
                final String localUid = person.localUid;
                try {
                    imageLoader.execute(() -> {
                        try {
                            Bitmap face = dbManager.getPersonFaceThumbnail(localUid, 256);
                            if (face == null) {
                                String imageUrl = dbManager.getPersonImageUrl(localUid);
                                if (imageUrl != null && !imageUrl.isEmpty()) {
                                    String token = holder.itemView.getContext().getApplicationContext()
                                            .getSharedPreferences("app_prefs", android.content.Context.MODE_PRIVATE)
                                            .getString("token", null);
                                    if (token != null && !token.isEmpty()) RetrofitClient.setAuthToken(token);
                                    byte[] bytes = RetrofitClient.downloadImage(imageUrl, 5 * 1024 * 1024);
                                    face = decodeThumbnail(bytes, 256);
                                    // Do not store a response that arrived after a newer sync URL.
                                    if (face != null) {
                                        if (!imageUrl.equals(dbManager.getPersonImageUrl(localUid))) {
                                            if (!face.isRecycled()) face.recycle();
                                            face = null;
                                        } else {
                                            dbManager.updatePersonPhotoByLocalUid(localUid, face);
                                        }
                                    }
                                }
                            }
                            if (face == null || released) return;
                            faceCache.put(key, face);
                            Bitmap loadedFace = face;
                            holder.imgFace.post(() -> {
                                if (!released && key.equals(holder.imgFace.getTag()) && !loadedFace.isRecycled()) {
                                    holder.imgFace.setImageBitmap(loadedFace);
                                }
                            });
                        } catch (Exception | OutOfMemoryError ignored) {
                        } finally {
                            imageLoadsInFlight.remove(key);
                        }
                    });
                } catch (java.util.concurrent.RejectedExecutionException ignored) {
                    imageLoadsInFlight.remove(key);
                }
            }
        }

        String idLabel = person.displayId > 0
                ? String.valueOf(person.displayId)
                : person.id != null && !person.id.isEmpty() ? person.id : String.valueOf(position + 1);
        StringBuilder details = new StringBuilder("ID: ").append(idLabel);
        if (person.department != null && !person.department.isEmpty()) details.append(" • ").append(person.department);
        if (person.designation != null && !person.designation.isEmpty()) details.append(" • ").append(person.designation);
        holder.tvDetails.setText(details.toString());

        holder.itemView.setOnClickListener(v -> {
            int adapterPosition = holder.getBindingAdapterPosition();
            if (clickListener != null && adapterPosition != RecyclerView.NO_POSITION && adapterPosition < userList.size()) {
                clickListener.onClickUser(userList.get(adapterPosition), adapterPosition);
            }
        });

        holder.itemView.setOnLongClickListener(v -> {
            int adapterPosition = holder.getBindingAdapterPosition();
            if (deleteListener != null && adapterPosition != RecyclerView.NO_POSITION && adapterPosition < userList.size()) {
                deleteListener.onDeleteUser(userList.get(adapterPosition), adapterPosition);
            }
            return true;
        });
    }

    @Override
    public void onViewRecycled(@NonNull UserViewHolder holder) {
        holder.imgFace.setTag(null);
        holder.imgFace.setImageResource(R.drawable.openvision_logo);
        super.onViewRecycled(holder);
    }

    @Override
    public int getItemCount() {
        return userList.size();
    }

    private int indexOf(Person person) {
        for (int i = 0; i < userList.size(); i++) if (samePerson(userList.get(i), person)) return i;
        return -1;
    }

    private static boolean samePerson(Person left, Person right) {
        if (left == right) return true;
        if (left == null || right == null) return false;
        if (left.localUid != null && right.localUid != null && left.localUid.equals(right.localUid)) return true;
        return left.id != null && right.id != null && !left.id.isEmpty() && left.id.equals(right.id);
    }

    private static String cacheKey(Person person) {
        if (person.localUid != null && !person.localUid.isEmpty()) return "local:" + person.localUid;
        if (person.id != null && !person.id.isEmpty()) return "id:" + person.id;
        return "name:" + Objects.toString(person.name, "unknown");
    }

    private static Bitmap decodeThumbnail(byte[] bytes, int maxDimension) {
        if (bytes == null || bytes.length == 0) return null;
        try {
            BitmapFactory.Options bounds = new BitmapFactory.Options();
            bounds.inJustDecodeBounds = true;
            BitmapFactory.decodeByteArray(bytes, 0, bytes.length, bounds);
            if (bounds.outWidth <= 0 || bounds.outHeight <= 0) return null;
            int sample = 1;
            int target = Math.max(64, maxDimension);
            while (bounds.outWidth / (sample * 2) >= target && bounds.outHeight / (sample * 2) >= target) {
                sample *= 2;
            }
            BitmapFactory.Options options = new BitmapFactory.Options();
            options.inSampleSize = sample;
            options.inPreferredConfig = Bitmap.Config.RGB_565;
            return BitmapFactory.decodeByteArray(bytes, 0, bytes.length, options);
        } catch (Exception | OutOfMemoryError ignored) {
            return null;
        }
    }

    static class UserViewHolder extends RecyclerView.ViewHolder {
        final ImageView imgFace;
        final TextView tvName;
        final TextView tvDetails;

        UserViewHolder(@NonNull View itemView) {
            super(itemView);
            imgFace = itemView.findViewById(R.id.img_face);
            tvName = itemView.findViewById(R.id.tv_name);
            tvDetails = itemView.findViewById(R.id.tv_details);
        }
    }
}
