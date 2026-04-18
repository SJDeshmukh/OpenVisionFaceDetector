import React, { useState, useEffect } from 'react';
import { Shield, CheckCircle, XCircle, Clock, Search, RefreshCw, Trash2 } from 'lucide-react';
import { API_URL } from '../config';
import axios from 'axios';

const FaceResetRequests = () => {
    const [requests, setRequests] = useState([]);
    const [loading, setLoading] = useState(true);
    const [searchTerm, setSearchTerm] = useState('');
    const [processingId, setProcessingId] = useState(null);

    const fetchRequests = async () => {
        setLoading(true);
        try {
            const token = localStorage.getItem('token');
            const response = await axios.get(`${API_URL}/admin/face-reset-requests`, {
                headers: { Authorization: `Bearer ${token}` }
            });
            if (response.data.status === 'success') {
                setRequests(response.data.requests);
            }
        } catch (error) {
            console.error('Error fetching requests:', error);
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        fetchRequests();
    }, []);

    const handleAction = async (requestId, action) => {
        if (!window.confirm(`Are you sure you want to ${action} this request?`)) return;

        setProcessingId(requestId);
        try {
            const token = localStorage.getItem('token');
            const response = await axios.post(`${API_URL}/admin/handle-face-reset`, {
                request_id: requestId,
                action: action
            }, {
                headers: { Authorization: `Bearer ${token}` }
            });

            if (response.data.status === 'success') {
                alert(response.data.message);
                fetchRequests();
            }
        } catch (error) {
            alert(error.response?.data?.error || 'Failed to process request');
        } finally {
            setProcessingId(null);
        }
    };

    const filteredRequests = requests.filter(req => 
        req.parent_username?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        req.student_number?.toLowerCase().includes(searchTerm.toLowerCase()) ||
        req.reason?.toLowerCase().includes(searchTerm.toLowerCase())
    );

    return (
        <div className="p-4 lg:p-8 bg-slate-50 min-h-screen">
            <div className="max-w-7xl mx-auto">
                <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 mb-8">
                    <div>
                        <h1 className="text-2xl font-bold text-slate-900">Face Reset Requests</h1>
                        <p className="text-slate-500">Manage parent requests to change their registered face</p>
                    </div>
                    <button 
                        onClick={fetchRequests}
                        className="flex items-center px-4 py-2 bg-white border border-slate-200 rounded-lg text-slate-600 hover:bg-slate-50 transition-colors shadow-sm"
                    >
                        <RefreshCw size={18} className={`mr-2 ${loading ? 'animate-spin' : ''}`} />
                        Refresh
                    </button>
                </div>

                <div className="bg-white rounded-xl shadow-sm border border-slate-200 overflow-hidden">
                    <div className="p-4 border-b border-slate-200 bg-slate-50/50">
                        <div className="relative max-w-md">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" size={18} />
                            <input
                                type="text"
                                placeholder="Search by username, student ID or reason..."
                                className="w-full pl-10 pr-4 py-2 border border-slate-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500/20 focus:border-blue-500 transition-all text-sm"
                                value={searchTerm}
                                onChange={(e) => setSearchTerm(e.target.value)}
                            />
                        </div>
                    </div>

                    <div className="overflow-x-auto">
                        <table className="w-full text-left">
                            <thead className="bg-slate-50 text-slate-500 text-xs uppercase font-semibold">
                                <tr>
                                    <th className="px-6 py-4">Parent / Username</th>
                                    <th className="px-6 py-4">Student ID</th>
                                    <th className="px-6 py-4">Reason</th>
                                    <th className="px-6 py-4">Requested On</th>
                                    <th className="px-6 py-4 text-right">Actions</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-slate-100">
                                {loading && requests.length === 0 ? (
                                    <tr>
                                        <td colSpan="5" className="px-6 py-12 text-center text-slate-400">
                                            <RefreshCw className="animate-spin mx-auto mb-2" size={24} />
                                            Loading requests...
                                        </td>
                                    </tr>
                                ) : filteredRequests.length === 0 ? (
                                    <tr>
                                        <td colSpan="5" className="px-6 py-12 text-center text-slate-400">
                                            {searchTerm ? 'No requests match your search' : 'No pending face reset requests'}
                                        </td>
                                    </tr>
                                ) : (
                                    filteredRequests.map((req) => (
                                        <tr key={req.id} className="hover:bg-slate-50/50 transition-colors">
                                            <td className="px-6 py-4">
                                                <div className="flex items-center">
                                                    <div className="w-8 h-8 rounded-full bg-blue-100 text-blue-600 flex items-center justify-center font-bold mr-3 text-xs">
                                                        {req.parent_username?.charAt(0).toUpperCase()}
                                                    </div>
                                                    <span className="font-medium text-slate-700">{req.parent_username}</span>
                                                </div>
                                            </td>
                                            <td className="px-6 py-4 text-slate-600 font-mono text-sm">{req.student_number}</td>
                                            <td className="px-6 py-4 text-slate-600 text-sm max-w-xs truncate">{req.reason || 'No reason provided'}</td>
                                            <td className="px-6 py-4 text-slate-500 text-xs text-nowrap">
                                                {new Date(req.created_at).toLocaleString()}
                                            </td>
                                            <td className="px-6 py-4 text-right">
                                                <div className="flex justify-end space-x-2">
                                                    <button
                                                        onClick={() => handleAction(req.id, 'approved')}
                                                        disabled={processingId === req.id}
                                                        className="p-2 text-green-600 hover:bg-green-50 rounded-lg transition-colors title='Approve & Reset Face'"
                                                    >
                                                        <Trash2 size={20} />
                                                    </button>
                                                    <button
                                                        onClick={() => handleAction(req.id, 'rejected')}
                                                        disabled={processingId === req.id}
                                                        className="p-2 text-red-600 hover:bg-red-50 rounded-lg transition-colors title='Reject Request'"
                                                    >
                                                        <XCircle size={20} />
                                                    </button>
                                                </div>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div className="mt-8 bg-blue-50 border border-blue-100 rounded-xl p-6">
                    <div className="flex items-start">
                        <Shield className="text-blue-600 mt-1 mr-4" size={24} />
                        <div>
                            <h3 className="text-lg font-bold text-blue-900 mb-1">Security Note</h3>
                            <p className="text-blue-800 text-sm opacity-90">
                                Approving a face reset request will **permanently delete** the parent's current face data. 
                                The parent will be forced to scan and register a new face during their next mobile app login. 
                                Use this only when you are certain the identity change is legitimate.
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
};

export default FaceResetRequests;
