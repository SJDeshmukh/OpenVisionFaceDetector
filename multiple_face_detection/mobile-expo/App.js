import React, { useCallback, useEffect, useRef, useState } from 'react';
import { NavigationContainer } from '@react-navigation/native';
import { createNativeStackNavigator } from '@react-navigation/native-stack';
import { View, Text, TouchableOpacity, FlatList, Image, Modal, TextInput, Dimensions } from 'react-native';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as FileSystem from 'expo-file-system';
import { Camera, CameraType } from 'expo-camera';
import * as FaceDetector from 'expo-face-detector';

const Stack = createNativeStackNavigator();
const KEY = 'photos_index_v1';
const API_BASE = 'http://127.0.0.1:5001';
const DEVICE_KEY = 'device_id_v1';

function useStore() {
  const load = useCallback(async () => {
    const s = await AsyncStorage.getItem(KEY);
    const arr = s ? JSON.parse(s) : [];
    return Array.isArray(arr) ? arr : [];
  }, []);
  const save = useCallback(async (items) => {
    await AsyncStorage.setItem(KEY, JSON.stringify(items));
  }, []);
  const add = useCallback(async (it) => {
    const items = await load();
    items.unshift(it);
    await save(items);
    return items;
  }, [load, save]);
  const remove = useCallback(async (id) => {
    const items = await load();
    const keep = items.filter(x => x.id !== id);
    await save(keep);
    return keep;
  }, [load, save]);
  const upsert = useCallback(async (id, patch) => {
    const items = await load();
    const out = items.map(x => x.id === id ? ({ ...x, ...patch }) : x);
    await save(out);
    return out;
  }, [load, save]);
  return { load, save, add, remove, upsert };
}

function HomeScreen({ navigation }) {
  return (
    <View style={{ flex: 1, backgroundColor: '#0f172a', padding: 20, justifyContent: 'space-between' }}>
      <View />
      <View style={{ alignItems: 'center' }}>
        <Text style={{ fontSize: 28, color: '#e2e8f0', fontWeight: '700', marginBottom: 6 }}>Face Capture</Text>
        <Text style={{ fontSize: 14, color: '#94a3b8' }}>On-device detection, auto-zoom, local labeling</Text>
      </View>
      <TouchableOpacity onPress={() => navigation.navigate('Camera')} style={{ backgroundColor: '#22c55e', paddingVertical: 18, borderRadius: 999, alignItems: 'center', marginBottom: 8 }}>
        <Text style={{ color: '#0b131f', fontSize: 18, fontWeight: '700' }}>Capture</Text>
      </TouchableOpacity>
      <TouchableOpacity onPress={() => navigation.navigate('ParentLogin')} style={{ backgroundColor: '#2563eb', paddingVertical: 14, borderRadius: 999, alignItems: 'center' }}>
        <Text style={{ color: '#fff', fontSize: 16, fontWeight: '700' }}>Parent Login</Text>
      </TouchableOpacity>
      <TouchableOpacity onPress={() => navigation.navigate('DeviceSetup')} style={{ backgroundColor: '#334155', paddingVertical: 12, borderRadius: 999, alignItems: 'center' }}>
        <Text style={{ color: '#e2e8f0', fontSize: 14, fontWeight: '700' }}>Device Setup</Text>
      </TouchableOpacity>
    </View>
  );
}

function CameraScreen({ navigation }) {
  const camRef = useRef(null);
  const [ready, setReady] = useState(false);
  const [permission, requestPermission] = Camera.useCameraPermissions();
  const [faces, setFaces] = useState([]);
  const [zoom, setZoom] = useState(0);
  const [ratio, setRatio] = useState('16:9');
  const [taking, setTaking] = useState(false);
  const store = useStore();
  const vw = Dimensions.get('window').width;
  const vh = Math.round(vw * 16 / 9);
  useEffect(() => {
    if (!permission || !permission.granted) requestPermission();
  }, []);
  const onFaces = useCallback(({ faces }) => {
    setFaces(faces || []);
  }, []);
  useEffect(() => {
    if (!faces || faces.length === 0) return;
    const f = faces[0];
    const w = f.bounds.size.width;
    const h = f.bounds.size.height;
    const target = 0.2;
    const frac = Math.min(1, Math.max(0, (w * h) / (vw * vh)));
    let desired = zoom;
    if (frac < target) desired = Math.min(1, zoom + 0.02);
    else if (frac > target * 1.4) desired = Math.max(0, zoom - 0.02);
    const smooth = 0.2;
    const z = zoom + smooth * (desired - zoom);
    setZoom(Number(z.toFixed(4)));
  }, [faces]);
  const take = useCallback(async () => {
    if (taking) return;
    setTaking(true);
    try {
      const cam = camRef.current;
      if (!cam) return;
      const pic = await cam.takePictureAsync({ quality: 0.9, skipProcessing: false });
      const id = Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
      const dir = FileSystem.documentDirectory + 'photos';
      await FileSystem.makeDirectoryAsync(dir, { intermediates: true }).catch(() => {});
      const dst = `${dir}/${id}.jpg`;
      await FileSystem.copyAsync({ from: pic.uri, to: dst });
      await store.add({ id, uri: dst, label: '', ts: Date.now() });
      navigation.replace('Gallery', { focusId: id });
    } catch (e) {
    } finally {
      setTaking(false);
    }
  }, [taking]);
  return (
    <View style={{ flex: 1, backgroundColor: '#0f172a' }}>
      {permission && permission.granted ? (
        <View style={{ flex: 1 }}>
          <View style={{ width: vw, height: vh, backgroundColor: '#000' }}>
            <Camera
              ref={camRef}
              style={{ width: vw, height: vh }}
              type={CameraType.front}
              onCameraReady={() => setReady(true)}
              ratio={ratio}
              zoom={zoom}
              autoFocus="on"
              onMountError={() => {}}
              faceDetectorSettings={{
                mode: FaceDetector.FaceDetectorMode.accurate,
                detectLandmarks: FaceDetector.FaceDetectorLandmarks.all,
                runClassifications: FaceDetector.FaceDetectorClassifications.none,
                minDetectionInterval: 100,
                tracking: true
              }}
              onFacesDetected={onFaces}
            />
            <View pointerEvents="none" style={{ position: 'absolute', left: 0, top: 0, width: vw, height: vh, alignItems: 'center', justifyContent: 'center' }}>
              <View style={{ width: 180, height: 180, borderRadius: 999, borderWidth: 2, borderColor: '#22c55e33', backgroundColor: '#22c55e11' }} />
            </View>
          </View>
          <View style={{ padding: 16, backgroundColor: '#0b1220', borderTopWidth: 1, borderTopColor: '#1f2937' }}>
            <TouchableOpacity onPress={take} disabled={!ready} style={{ alignSelf: 'center', backgroundColor: ready ? '#22c55e' : '#64748b', width: 84, height: 84, borderRadius: 999, alignItems: 'center', justifyContent: 'center' }}>
              <View style={{ width: 64, height: 64, borderRadius: 999, backgroundColor: '#0b131f' }} />
            </TouchableOpacity>
            <View style={{ marginTop: 12, alignItems: 'center', flexDirection: 'row', justifyContent: 'center', gap: 12 }}>
              <TouchableOpacity onPress={() => setZoom(z => Math.max(0, Number((z - 0.05).toFixed(2))))} style={{ paddingVertical: 10, paddingHorizontal: 16, backgroundColor: '#334155', borderRadius: 8 }}>
                <Text style={{ color: '#e2e8f0', fontSize: 16 }}>-</Text>
              </TouchableOpacity>
              <Text style={{ color: '#94a3b8' }}>Zoom: {(zoom * 100 | 0)}%</Text>
              <TouchableOpacity onPress={() => setZoom(z => Math.min(1, Number((z + 0.05).toFixed(2))))} style={{ paddingVertical: 10, paddingHorizontal: 16, backgroundColor: '#334155', borderRadius: 8 }}>
                <Text style={{ color: '#e2e8f0', fontSize: 16 }}>+</Text>
              </TouchableOpacity>
            </View>
            <View style={{ marginTop: 6, alignItems: 'center' }}>
              <Text style={{ color: '#94a3b8' }}>{faces.length > 0 ? 'Align face inside circle' : 'Searching for face'}</Text>
            </View>
          </View>
        </View>
      ) : (
        <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
          <Text style={{ color: '#e2e8f0' }}>Camera permission required</Text>
        </View>
      )}
    </View>
  );
}

function GalleryScreen({ route, navigation }) {
  const store = useStore();
  const [items, setItems] = useState([]);
  const [edit, setEdit] = useState(null);
  const load = useCallback(async () => {
    const arr = await store.load();
    setItems(arr);
  }, []);
  useEffect(() => {
    load();
  }, []);
  useEffect(() => {
    if (!route?.params?.focusId) return;
    setTimeout(() => {}, 0);
  }, [route?.params?.focusId]);
  const del = useCallback(async (id) => {
    const it = items.find(x => x.id === id);
    await store.remove(id);
    if (it && it.uri) {
      try { await FileSystem.deleteAsync(it.uri, { idempotent: true }); } catch (e) {}
    }
    load();
  }, [items]);
  const saveLabel = useCallback(async (id, label) => {
    await store.upsert(id, { label });
    setEdit(null);
    load();
  }, []);
  const renderItem = useCallback(({ item }) => {
    return (
      <View style={{ marginBottom: 12, backgroundColor: '#0b1220', borderRadius: 12, overflow: 'hidden', borderWidth: 1, borderColor: '#1f2937' }}>
        <Image source={{ uri: item.uri }} style={{ width: '100%', height: 260, backgroundColor: '#000' }} resizeMode="cover" />
        <View style={{ padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
          <View style={{ flex: 1 }}>
            <Text style={{ color: '#e2e8f0', fontSize: 16, fontWeight: '600' }}>{item.label || 'Unlabeled'}</Text>
            <Text style={{ color: '#64748b', fontSize: 12 }}>{new Date(item.ts).toLocaleString()}</Text>
          </View>
          <TouchableOpacity onPress={() => setEdit({ id: item.id, label: item.label || '' })} style={{ paddingVertical: 8, paddingHorizontal: 12, backgroundColor: '#2563eb', borderRadius: 8, marginRight: 8 }}>
            <Text style={{ color: '#fff' }}>Edit</Text>
          </TouchableOpacity>
          <TouchableOpacity onPress={() => del(item.id)} style={{ paddingVertical: 8, paddingHorizontal: 12, backgroundColor: '#ef4444', borderRadius: 8 }}>
            <Text style={{ color: '#fff' }}>Delete</Text>
          </TouchableOpacity>
        </View>
      </View>
    );
  }, [items]);
  return (
    <View style={{ flex: 1, backgroundColor: '#0f172a', padding: 14 }}>
      <FlatList
        data={items}
        keyExtractor={it => it.id}
        renderItem={renderItem}
      />
      <TouchableOpacity onPress={() => navigation.navigate('Camera')} style={{ position: 'absolute', right: 18, bottom: 24, backgroundColor: '#22c55e', width: 62, height: 62, borderRadius: 999, alignItems: 'center', justifyContent: 'center' }}>
        <View style={{ width: 36, height: 36, borderRadius: 999, backgroundColor: '#0b131f' }} />
      </TouchableOpacity>
      <Modal visible={!!edit} transparent>
        <View style={{ flex: 1, backgroundColor: '#0009', alignItems: 'center', justifyContent: 'center', padding: 20 }}>
          <View style={{ backgroundColor: '#0b1220', padding: 16, borderRadius: 12, width: '100%', borderWidth: 1, borderColor: '#1f2937' }}>
            <Text style={{ color: '#e2e8f0', fontSize: 16, fontWeight: '700', marginBottom: 8 }}>Edit Label</Text>
            <TextInput
              autoFocus
              placeholder="Enter label"
              placeholderTextColor="#64748b"
              value={edit?.label || ''}
              onChangeText={(t) => setEdit(edit ? { ...edit, label: t } : null)}
              style={{ color: '#e2e8f0', borderWidth: 1, borderColor: '#334155', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 8, marginBottom: 12 }}
            />
            <View style={{ flexDirection: 'row', justifyContent: 'flex-end' }}>
              <TouchableOpacity onPress={() => setEdit(null)} style={{ paddingVertical: 10, paddingHorizontal: 14, backgroundColor: '#334155', borderRadius: 8, marginRight: 8 }}>
                <Text style={{ color: '#e2e8f0' }}>Cancel</Text>
              </TouchableOpacity>
              <TouchableOpacity onPress={() => saveLabel(edit.id, edit.label)} style={{ paddingVertical: 10, paddingHorizontal: 14, backgroundColor: '#2563eb', borderRadius: 8 }}>
                <Text style={{ color: '#fff' }}>Save</Text>
              </TouchableOpacity>
            </View>
          </View>
        </View>
      </Modal>
    </View>
  );
}

function ParentLoginScreen({ navigation }) {
  const [studentId, setStudentId] = useState('');
  return (
    <View style={{ flex: 1, backgroundColor: '#0f172a', padding: 20, justifyContent: 'center' }}>
      <Text style={{ color: '#e2e8f0', fontSize: 22, fontWeight: '700', marginBottom: 12 }}>Parent Login</Text>
      <Text style={{ color: '#94a3b8', marginBottom: 10 }}>Enter Student ID to view check-in/out locations</Text>
      <TextInput
        placeholder="Student ID"
        placeholderTextColor="#64748b"
        value={studentId}
        onChangeText={setStudentId}
        style={{ color: '#e2e8f0', borderWidth: 1, borderColor: '#334155', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, marginBottom: 12 }}
      />
      <TouchableOpacity onPress={() => { if (studentId.trim()) navigation.replace('ParentEvents', { studentId: studentId.trim() }); }} style={{ backgroundColor: '#2563eb', paddingVertical: 14, borderRadius: 8, alignItems: 'center' }}>
        <Text style={{ color: '#fff', fontSize: 16, fontWeight: '700' }}>View Locations</Text>
      </TouchableOpacity>
    </View>
  );
}

function ParentEventsScreen({ route }) {
  const sid = route?.params?.studentId || '';
  const [items, setItems] = useState([]);
  const [loading, setLoading] = useState(false);
  const load = useCallback(async () => {
    if (!sid) return;
    setLoading(true);
    try {
      const r = await fetch(`${API_BASE}/student_check_events?student_id=${encodeURIComponent(sid)}`);
      if (r.ok) {
        const j = await r.json();
        setItems(Array.isArray(j.items) ? j.items : []);
      }
    } catch (e) {
    } finally {
      setLoading(false);
    }
  }, [sid]);
  useEffect(() => { load(); }, [sid]);
  const renderItem = ({ item }) => {
    const dt = new Date((item.timestamp || 0) * 1000);
    const title = `${item.event === 'check_in' ? 'Check-In' : 'Check-Out'}`;
    const subtitle = `${dt.toLocaleString()} • (${Number(item.lat).toFixed(5)}, ${Number(item.lng).toFixed(5)})${item.place ? ' • ' + item.place : ''}`;
    return (
      <View style={{ padding: 12, borderBottomWidth: 1, borderBottomColor: '#1f2937' }}>
        <Text style={{ color: '#e2e8f0', fontSize: 16, fontWeight: '600' }}>{title}</Text>
        <Text style={{ color: '#94a3b8', marginTop: 4 }}>{subtitle}</Text>
      </View>
    );
  };
  return (
    <View style={{ flex: 1, backgroundColor: '#0f172a' }}>
      <View style={{ padding: 16, borderBottomWidth: 1, borderBottomColor: '#1f2937' }}>
        <Text style={{ color: '#e2e8f0', fontSize: 18, fontWeight: '700' }}>Locations for {sid}</Text>
        {loading ? <Text style={{ color: '#94a3b8', marginTop: 8 }}>Loading…</Text> : null}
      </View>
      <FlatList data={items} keyExtractor={it => it.id} renderItem={renderItem} />
    </View>
  );
}

function DeviceSetupScreen() {
  const [deviceId, setDeviceId] = useState('');
  const [collegeId, setCollegeId] = useState('');
  const [places, setPlaces] = useState([]);
  const [assignment, setAssignment] = useState(null);
  const initDevice = useCallback(async () => {
    try {
      let d = await AsyncStorage.getItem(DEVICE_KEY);
      if (!d) {
        d = Date.now().toString(36) + Math.random().toString(36).slice(2, 10);
        await AsyncStorage.setItem(DEVICE_KEY, d);
      }
      setDeviceId(d);
    } catch (e) {}
  }, []);
  useEffect(() => { initDevice(); }, []);
  const loadPlaces = useCallback(async () => {
    try {
      const url = `${API_BASE}/places${collegeId ? `?college_id=${encodeURIComponent(collegeId)}` : ''}`;
      const r = await fetch(url);
      if (r.ok) {
        const j = await r.json();
        setPlaces(Array.isArray(j.items) ? j.items : []);
      }
    } catch (e) {}
  }, [collegeId]);
  useEffect(() => { loadPlaces(); }, [collegeId]);
  const loadAssignment = useCallback(async () => {
    if (!deviceId) return;
    try {
      const url = `${API_BASE}/device_assignment?device_id=${encodeURIComponent(deviceId)}${collegeId ? `&college_id=${encodeURIComponent(collegeId)}` : ''}`;
      const r = await fetch(url);
      if (r.ok) {
        const j = await r.json();
        setAssignment(j.assignment || null);
      }
    } catch (e) {}
  }, [deviceId, collegeId]);
  useEffect(() => { loadAssignment(); }, [deviceId, collegeId]);
  const assign = useCallback(async (pid) => {
    if (!deviceId || !pid) return;
    try {
      const r = await fetch(`${API_BASE}/device_assign`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ device_id: deviceId, college_id: collegeId, place_id: pid })
      });
      if (r.ok) {
        const j = await r.json();
        setAssignment(j.assignment || null);
      }
    } catch (e) {}
  }, [deviceId, collegeId]);
  return (
    <View style={{ flex: 1, backgroundColor: '#0f172a', padding: 16 }}>
      <Text style={{ color: '#e2e8f0', fontSize: 18, fontWeight: '700', marginBottom: 12 }}>Device Setup</Text>
      <Text style={{ color: '#94a3b8', marginBottom: 8 }}>Device ID: {deviceId || '...'}</Text>
      <TextInput
        placeholder="College ID (optional)"
        placeholderTextColor="#64748b"
        value={collegeId}
        onChangeText={setCollegeId}
        style={{ color: '#e2e8f0', borderWidth: 1, borderColor: '#334155', borderRadius: 8, paddingHorizontal: 12, paddingVertical: 10, marginBottom: 12 }}
      />
      <View style={{ backgroundColor: '#0b1220', borderWidth: 1, borderColor: '#1f2937', borderRadius: 12, padding: 12 }}>
        <Text style={{ color: '#e2e8f0', fontWeight: '600', marginBottom: 8 }}>Registered Places</Text>
        {places.length === 0 ? <Text style={{ color: '#94a3b8' }}>No places found</Text> : null}
        {places.map(p => (
          <View key={p.id} style={{ paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: '#1f2937' }}>
            <Text style={{ color: '#e2e8f0' }}>{p.name}</Text>
            <TouchableOpacity onPress={() => assign(p.id)} style={{ marginTop: 6, paddingVertical: 8, paddingHorizontal: 12, backgroundColor: '#2563eb', borderRadius: 8, alignSelf: 'flex-start' }}>
              <Text style={{ color: '#fff' }}>Assign</Text>
            </TouchableOpacity>
          </View>
        ))}
      </View>
      <View style={{ marginTop: 16, backgroundColor: '#0b1220', borderWidth: 1, borderColor: '#1f2937', borderRadius: 12, padding: 12 }}>
        <Text style={{ color: '#e2e8f0', fontWeight: '600', marginBottom: 8 }}>Current Assignment</Text>
        {assignment ? (
          <Text style={{ color: '#94a3b8' }}>{assignment.place_name} ({assignment.place_id})</Text>
        ) : (
          <Text style={{ color: '#94a3b8' }}>None</Text>
        )}
      </View>
    </View>
  );
}

export default function App() {
  return (
    <NavigationContainer>
      <Stack.Navigator screenOptions={{ headerStyle: { backgroundColor: '#0b1220' }, headerTintColor: '#e2e8f0', contentStyle: { backgroundColor: '#0f172a' } }}>
        <Stack.Screen name="Home" component={HomeScreen} options={{ title: 'Home' }} />
        <Stack.Screen name="Camera" component={CameraScreen} options={{ title: 'Capture' }} />
        <Stack.Screen name="Gallery" component={GalleryScreen} options={{ title: 'Gallery' }} />
        <Stack.Screen name="ParentLogin" component={ParentLoginScreen} options={{ title: 'Parent Login' }} />
        <Stack.Screen name="ParentEvents" component={ParentEventsScreen} options={{ title: 'Locations' }} />
        <Stack.Screen name="DeviceSetup" component={DeviceSetupScreen} options={{ title: 'Device Setup' }} />
      </Stack.Navigator>
    </NavigationContainer>
  );
}
