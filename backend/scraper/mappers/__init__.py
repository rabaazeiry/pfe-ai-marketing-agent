"""Mappers translate NormalizedPost lists into payloads matching the
existing Mongo models (Competitor, SocialAnalysis, Insight).

Mappers never write to Mongo themselves — the Node backend does the
persistence using its Mongoose models.
"""
