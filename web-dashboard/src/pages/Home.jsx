import { motion } from 'framer-motion';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import logo from '../assets/logo_openvision.png';

const Home = () => {
  const navigate = useNavigate();

  return (
    <div className="min-h-screen flex flex-col items-center justify-center text-center px-4 relative z-10 text-white">
      <motion.div
        initial={{ opacity: 0, y: 20 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.8 }}
        className="max-w-4xl mx-auto"
      >
        <div className="flex justify-center mb-8">
          <div className="relative">
            <div className="absolute inset-0 bg-blue-500 blur-2xl opacity-20 rounded-full"></div>
            <img src={logo} alt="VisionX" className="w-32 h-32 relative z-10 object-contain" />
          </div>
        </div>

        <h1 className="text-6xl font-bold mb-2 bg-clip-text text-transparent bg-gradient-to-r from-blue-400 via-purple-400 to-pink-400">
          VisionX
        </h1>
        <p className="text-xl text-blue-300 font-medium mb-6">Powered by OpenVision</p>
        
        <p className="text-xl text-gray-300 mb-10 max-w-2xl mx-auto leading-relaxed">
          Experience the future of attendance management with our AI-powered Face Recognition solution. 
          Seamless, secure, and real-time.
        </p>

        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.95 }}
          onClick={() => navigate('/dashboard')}
          className="group bg-white/10 hover:bg-white/20 backdrop-blur-sm border border-white/20 text-white px-8 py-4 rounded-full font-semibold text-lg flex items-center space-x-3 mx-auto transition-all"
        >
          <span>Launch Dashboard</span>
          <ArrowRight className="group-hover:translate-x-1 transition-transform" />
        </motion.button>
      </motion.div>

      {/* Stats Preview */}
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        transition={{ delay: 0.5, duration: 1 }}
        className="absolute bottom-10 left-0 right-0 flex justify-center space-x-12 text-gray-400"
      >
        <div className="text-center">
          <p className="text-3xl font-bold text-white">99.9%</p>
          <p className="text-sm">Accuracy</p>
        </div>
        <div className="text-center">
          <p className="text-3xl font-bold text-white">Real-time</p>
          <p className="text-sm">Sync</p>
        </div>
        <div className="text-center">
          <p className="text-3xl font-bold text-white">Secure</p>
          <p className="text-sm">Encryption</p>
        </div>
      </motion.div>
    </div>
  );
};

export default Home;