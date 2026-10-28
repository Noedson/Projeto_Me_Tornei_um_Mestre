-- Cria o usuário e o banco de dados do ChirpStack no mesmo servidor PostgreSQL do Django
create role chirpstack with login password 'chirpstack';
create database chirpstack with owner chirpstack;

\c chirpstack

create extension pg_trgm;
create extension hstore;

