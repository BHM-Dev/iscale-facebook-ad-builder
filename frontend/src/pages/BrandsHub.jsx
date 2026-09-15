import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, ShoppingBag, Package, Users } from 'lucide-react';

const TOOLS = [
  { path: '/brands', icon: ShoppingBag, title: 'Brands', description: 'Create and manage the brands used across your ad workflows.' },
  { path: '/products', icon: Package, title: 'Products', description: 'Manage the products and offers attached to each brand.' },
  { path: '/profiles', icon: Users, title: 'Customer Profiles', description: 'Define the audiences and avatars used for copy and creative generation.' },
];

export default function BrandsHub() {
  const navigate = useNavigate();
  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-8">
        <h1 className="text-3xl font-bold text-gray-900">Brands</h1>
        <p className="text-gray-600 mt-2">Manage your brand building blocks</p>
      </div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {TOOLS.map(tool => {
          const Icon = tool.icon;
          return (
            <button key={tool.path} onClick={() => navigate(tool.path)} className="group relative flex flex-col items-start p-8 bg-white rounded-2xl border-2 border-gray-100 hover:border-gray-300 hover:shadow-xl transition-all duration-300 text-left">
              <div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-5 group-hover:scale-110 transition-transform duration-300"><Icon size={28} className="text-gray-700" /></div>
              <h3 className="text-xl font-bold text-gray-900 mb-2">{tool.title}</h3>
              <p className="text-gray-500 text-sm leading-relaxed flex-1">{tool.description}</p>
              <div className="mt-6 flex items-center gap-2 text-sm font-semibold text-gray-900 group-hover:gap-3 transition-all">Open <ArrowRight size={16} /></div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
