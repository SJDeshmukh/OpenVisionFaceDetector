import { useCallback, useState, useEffect } from 'react';
import axios from 'axios';
import { Search, Trash2 } from 'lucide-react';
import { API_URL } from '../config';
import { useSocket } from '../context/SocketContext';
import { useAuth } from '../context/AuthContext';

const Users = () => {
  const { user } = useAuth();
  const { socket } = useSocket();
  const [users, setUsers] = useState([]);
  const [search, setSearch] = useState('');

  const fetchData = useCallback(async () => {
    try {
      const res = await axios.get(`${API_URL}/sync/download`);
      setUsers(res.data.faces || []);
    } catch (error) {
      console.error("Error fetching users:", error);
    }
  }, []);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  useEffect(() => {
    if (!user || !socket) return;
    const handlePersonsUpdated = (data) => {
      if (String(data.vendor_id) === String(user.vendor_id)) {
        fetchData();
      }
    };
    socket.on('persons_updated', handlePersonsUpdated);
    return () => {
      socket.off('persons_updated', handlePersonsUpdated);
    };
  }, [fetchData, user, socket]);

  const deleteUser = async (person) => {
    if (!person.id || !window.confirm(`Delete ${person.name || 'this user'}?`)) return;
    try {
      await axios.delete(`${API_URL}/sync/delete/id/${person.id}`);
      setUsers((current) => current.filter((entry) => String(entry.id) !== String(person.id)));
    } catch (error) {
      console.error("Error deleting user:", error);
    }
  };

  const filteredUsers = users.filter(user => 
    (user.name || '').toLowerCase().includes(search.toLowerCase())
  );

  return (
    <div className="pt-24 px-8 pb-8 min-h-screen text-white">
      <div className="max-w-7xl mx-auto">
        <header className="mb-8 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
              Registered Users
            </h1>
            <p className="text-gray-400 mt-2">Manage enrolled faces</p>
          </div>
          
          <div className="relative">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" size={20} />
            <input 
              type="text" 
              placeholder="Search users..." 
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="bg-white/5 border border-white/10 rounded-full pl-10 pr-6 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500/50 focus:ring-1 focus:ring-blue-500/50 transition-all w-full md:w-64"
            />
          </div>
        </header>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-6">
          {filteredUsers.map((user) => (
            <div key={user.id || user.local_uid || user.name} className="group bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl p-6 hover:bg-white/10 transition-all duration-300 relative overflow-hidden">
              <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-500 to-purple-500 opacity-0 group-hover:opacity-100 transition-opacity"></div>
              
              <div className="flex justify-center mb-6 relative">
                <div className="w-24 h-24 rounded-full p-1 bg-gradient-to-br from-blue-500/20 to-purple-500/20">
                  <img 
                    src={`data:image/jpeg;base64,${user.face_image}`} 
                    alt={user.name} 
                    className="w-full h-full rounded-full object-cover border-2 border-white/10 group-hover:border-blue-400/50 transition-colors"
                  />
                </div>
                <div className="absolute bottom-0 right-1/2 translate-x-10 translate-y-2 bg-green-500 text-black text-[10px] font-bold px-2 py-0.5 rounded-full border border-white/10">
                  ACTIVE
                </div>
              </div>

              <div className="text-center">
                <h3 className="text-lg font-semibold text-white mb-1">{user.name}</h3>
                <p className="text-sm text-gray-400 mb-4">ID: {user.display_id || user.id || '—'}</p>
                
                <div className="flex justify-center space-x-2">
                  <button onClick={() => deleteUser(user)} aria-label={`Delete ${user.name || 'user'}`} className="p-2 rounded-lg bg-red-500/10 hover:bg-red-500/20 text-red-400 transition-colors">
                    <Trash2 size={18} />
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>

        {filteredUsers.length === 0 && (
          <div className="text-center py-20 text-gray-500">
            No users found matching "{search}"
          </div>
        )}
      </div>
    </div>
  );
};

export default Users;
