-- Dados fictícios para apresentação. Executado apenas ao criar o volume.
CREATE SCHEMA locacao;

CREATE TABLE locacao.imoveis (
    imovel_id SERIAL PRIMARY KEY,
    descricao VARCHAR(200) NOT NULL,
    bairro VARCHAR(80) NOT NULL,
    tipo VARCHAR(40) NOT NULL,
    quartos INTEGER NOT NULL CHECK (quartos BETWEEN 0 AND 50),
    valor_mensal NUMERIC(10,2) NOT NULL CHECK (valor_mensal > 0)
);

CREATE TABLE locacao.pedidos (
    pedido_id SERIAL PRIMARY KEY,
    cliente VARCHAR(120) NOT NULL,
    imovel_id INTEGER NOT NULL REFERENCES locacao.imoveis(imovel_id),
    data_solicitacao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    situacao VARCHAR(20) NOT NULL DEFAULT 'pendente'
        CHECK (situacao IN ('pendente','aprovado','recusado','cancelado','concluido'))
);

-- Só um pedido aprovado OU concluído pode ocupar cada imóvel.
CREATE UNIQUE INDEX uma_ocupacao_por_imovel ON locacao.pedidos(imovel_id)
    WHERE situacao IN ('aprovado', 'concluido');

CREATE TABLE locacao.avaliacoes (
    avaliacao_id SERIAL PRIMARY KEY,
    pedido_id INTEGER NOT NULL UNIQUE REFERENCES locacao.pedidos(pedido_id),
    nota INTEGER NOT NULL CHECK (nota BETWEEN 1 AND 5),
    comentario VARCHAR(500) NOT NULL,
    data_avaliacao TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- A situação é calculada para não ficar diferente da situação do pedido.
CREATE VIEW locacao.vw_imoveis AS
SELECT i.*, CASE p.situacao
    WHEN 'aprovado' THEN 'reservado'
    WHEN 'concluido' THEN 'alugado'
    ELSE 'disponivel' END AS situacao
FROM locacao.imoveis i LEFT JOIN locacao.pedidos p
ON i.imovel_id = p.imovel_id AND p.situacao IN ('aprovado', 'concluido');

CREATE VIEW locacao.vw_avaliacoes AS
SELECT a.*, p.cliente, p.imovel_id
FROM locacao.avaliacoes a JOIN locacao.pedidos p ON a.pedido_id = p.pedido_id;

INSERT INTO locacao.imoveis (descricao, bairro, tipo, quartos, valor_mensal) VALUES
('Apartamento próximo à praça', 'Centro', 'apartamento', 2, 1200),
('Casa com quintal', 'São José', 'casa', 3, 1800),
('Kitnet perto do campus', 'Universitário', 'kitnet', 1, 650),
('Apartamento com varanda', 'Centro', 'apartamento', 2, 1500),
('Casa térrea com garagem', 'Primavera', 'casa', 2, 1100),
('Apartamento compacto', 'São José', 'apartamento', 1, 850);

INSERT INTO locacao.pedidos (cliente, imovel_id, situacao) VALUES
('Ana Souza', 1, 'pendente'), ('Bruno Lima', 1, 'pendente'),
('Carla Santos', 2, 'aprovado'), ('Diego Alves', 3, 'concluido'),
('Elisa Costa', 4, 'recusado'), ('Felipe Rocha', 5, 'cancelado');

INSERT INTO locacao.avaliacoes (pedido_id, nota, comentario)
VALUES (4, 5, 'Imóvel bem localizado e atendimento atencioso.');
