import axios from 'axios';

const BASE_URL = process.env.REACT_APP_API_URL || 'http://localhost:8000';

const api = axios.create({ baseURL: BASE_URL });

export const askQuery = (query, topic = null) => {
  const params = { query };
  if (topic) params.topic = topic;
  return api.get('/ask', { params });
};

export const getVisualizationData = (params = {}) =>
  api.get('/visualization', { params: { limit: 300, ...params } });

export const uploadCircular = (file, topic, title = null) => {
  const form = new FormData();
  form.append('file', file);
  form.append('topic', topic);
  if (title) form.append('title', title);
  return api.post('/upload', form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  });
};

export const checkCompliance = (data, topic = null, entity_type = null) => {
  const body = { data };
  if (topic) body.topic = topic;
  if (entity_type) body.entity_type = entity_type;
  return api.post('/compliance', body);
};

export const getTopics = () => api.get('/topics');

export const getRules = (params = {}) => api.get('/rules', { params });

export const testServices = () => api.get('/test');

export const TOPIC_COLORS = {
  commercial_banks:                 '#378ADD',
  NBFC:                             '#7F77DD',
  payment_banks:                    '#1D9E75',
  small_financial_banks:            '#639922',
  Regional_Rural_Bank:              '#BA7517',
  local_area_banks:                 '#BA7517',
  Urban_Cooperative_Bank:           '#D85A30',
  Rural_Cooperative_Bank:           '#D85A30',
  All_India_Financial_Institutions: '#D4537E',
  Asset_Reconstruction_Companies:   '#E24B4A',
  Credit_Information_Services:      '#888780',
  KYC:                              '#1D9E75',
  AML:                              '#D85A30',
  PMLA:                             '#D85A30',
  forex:                            '#7F77DD',
  governance:                       '#888780',
  general:                          '#888780',
};

export const FOLDER_SUBTOPICS = {
  commercial_banks:                 ['credit','deposits','NPA','capital_adequacy','interest_rate'],
  NBFC:                             ['registration','prudential_norms','fair_practices','systemic_risk'],
  payment_banks:                    ['operations','deposit_limits','KYC','digital_payments'],
  small_financial_banks:            ['lending','priority_sector','deposits','KYC'],
  Regional_Rural_Bank:              ['agricultural_credit','priority_sector','refinance'],
  local_area_banks:                 ['operations','capital','lending'],
  Urban_Cooperative_Bank:           ['governance','audit','deposits','lending'],
  Rural_Cooperative_Bank:           ['agricultural_credit','governance','audit'],
  All_India_Financial_Institutions: ['long_term_finance','infrastructure','bonds'],
  Asset_Reconstruction_Companies:   ['securitisation','NPA_acquisition','resolution'],
  Credit_Information_Services:      ['credit_report','data_submission','dispute_resolution'],
  KYC:                              ['small_account','re_kyc','video_kyc','aadhaar_kyc'],
  AML:                              ['suspicious_transactions','cash_transactions','STR','CTR'],
  PMLA:                             ['record_keeping','beneficial_ownership','reporting'],
  forex:                            ['FEMA','remittance','import_export','ECB'],
  governance:                       ['board_composition','audit','disclosure','risk_management'],
  general:                          ['miscellaneous'],
};

export default api;
