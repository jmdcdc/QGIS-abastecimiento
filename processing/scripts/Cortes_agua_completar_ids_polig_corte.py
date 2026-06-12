# -*- coding: utf-8 -*-

# Importamos los módulos esenciales del núcleo de la API de QGIS Core
from qgis.core import (
    QgsProcessingAlgorithm,
    QgsProcessingParameterVectorLayer,
    QgsProcessingParameterField,
    QgsProcessingParameterFeatureSink,
    QgsFeatureSink,
    QgsWkbTypes,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsSpatialIndex
)

class CompletarIdentificadoresAlgoritmo(QgsProcessingAlgorithm):
    """
    Esta clase implementa la lógica de procesamiento heredando de QgsProcessingAlgorithm.
    Permite empaquetar el script para que QGIS lo renderice automáticamente en su 
    caja de herramientas de procesos con un diseño nativo.
    """
    
    # Definimos constantes como buenas prácticas para no cometer errores tipográficos
    INPUT = 'INPUT'
    FIELD_1 = 'FIELD_1'
    FIELD_2 = 'FIELD_2'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        """
        Inicializa y construye los campos y selectores de la ventana del algoritmo.
        """
        # Entrada: Capa de líneas (restringe la selección solo a geometrías tipo línea/multilínea)
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.INPUT,
                'Capa de tramos de red',
                [QgsWkbTypes.LineGeometry]
            )
        )
        # Campos: Selectores dinámicos vinculados directamente al esquema de la capa seleccionada
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_1,
                'Primer campo con valores nulos',
                parentLayerParameterName=self.INPUT
            )
        )
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_2,
                'Segundo campo con valores nulos',
                parentLayerParameterName=self.INPUT
            )
        )
        # Salida: Define el sumidero donde se escribirá el archivo final resultante (.shp)
        self.addParameter(
            QgsProcessingParameterFeatureSink(
                self.OUTPUT,
                'Tramos de red completados'
            )
        )

    def shortHelpString(self):
        """
        Contenido didáctico en HTML estructurado para la sección de ayuda de la interfaz gráfica.
        """
        return (
            "<h2>Instrucciones de uso:</h2>"
            "<p>Este script rellena valores nulos basándose en la conectividad espacial de la red.</p>"
            "<ol>"
            "<li>Seleccione la capa de tramos de red (admite líneas simples y multilíneas).</li>"
            "<li>Elija los dos campos que contienen los identificadores faltantes (valores NULL o vacíos).</li>"
            "<li>El algoritmo analizará recursivamente los extremos (máximo 8 iteraciones) para propagar los ID desde los tramos conectados.</li>"
            "</ol>"
        )

    # Definición de metadatos requeridos por QGIS para indexar la herramienta en la Caja de Herramientas
    def name(self):
        return 'cortes_agua_completar_identificadores'  # Identificador único interno

    def displayName(self):
        return 'Cortes agua - Completar identificadores de polígonos de corte'  # Nombre visible

    def group(self):
        return 'Aquavall - Abastecimiento'  # Nombre del bloque de herramientas

    def groupId(self):
        return 'aquavall_abastecimiento'  # ID jerárquico del bloque

    def createInstance(self):
        return CompletarIdentificadoresAlgoritmo()

    def processAlgorithm(self, parameters, context, feedback):
        """
        Núcleo operativo del algoritmo. Ejecuta las consultas espaciales iterativas.
        """
        # Extraemos los valores capturados de la interfaz de usuario
        layer = self.parameterAsVectorLayer(parameters, self.INPUT, context)
        f1 = self.parameterAsString(parameters, self.FIELD_1, context)
        f2 = self.parameterAsString(parameters, self.FIELD_2, context)

        # DIDÁCTICO: Cargamos todas las entidades del Shapefile en un diccionario en memoria ram.
        # Modificar atributos sobre diccionarios nativos de Python es miles de veces más rápido
        # que abrir sesiones de edición espacial con layer.startEditing() directamente en disco.
        features_dict = {f.id(): QgsFeature(f) for f in layer.getFeatures()}
        fields = layer.fields()
        
        # Localizamos la posición numérica de las columnas para interactuar con ellas mediante índices de atributos
        idx1 = fields.indexOf(f1)
        idx2 = fields.indexOf(f2)

        # TOLERANCIA TOPOLÓGICA (0.10 metros = 10 centímetros)
        # Dado que trabajamos sobre EPSG:25830 (UTM 30N), la unidad interna es el metro.
        TOLERANCIA = 0.10 

        # BUCLE PRINCIPAL DE PROPAGACIÓN: Ampliado a un máximo de 8 iteraciones (pases)
        # Esto soluciona colas consecutivas muy largas de tramos huerfanos (efecto dominó).
        for iteracion in range(1, 9):
            feedback.setProgressText(f"Iniciando iteración {iteracion}/8...")
            
            # DIDÁCTICO: Inicializamos un Índice Espacial (árbol R-Tree de GEOS) exclusivo para los tramos válidos.
            # Al reconstruirlo en cada ciclo, los elementos rescatados en la iteración previa
            # se convierten automáticamente en "donantes válidos" para la siguiente iteración.
            index_validos = QgsSpatialIndex()
            tramos_validos_dict = {}
            
            for feat_id, feat in features_dict.items():
                val1 = feat.attribute(idx1)
                val2 = feat.attribute(idx2)
                
                # Un tramo es donante válido si NO es nulo ni está vacío en ninguno de los dos campos
                es_valido_1 = val1 is not None and str(val1) != 'NULL' and str(val1).strip() != ''
                es_valido_2 = val2 is not None and str(val2) != 'NULL' and str(val2).strip() != ''
                
                if es_valido_1 and es_valido_2:
                    index_validos.addFeature(feat)  # Registramos la geometría en la estructura espacial indexada
                    tramos_validos_dict[feat_id] = feat  # Guardamos la referencia para consultar atributos

            cambios_en_iteracion = 0

            # Recorremos el diccionario buscando únicamente los tramos que aún posean valores nulos
            for feat_id, feat in features_dict.items():
                val1 = feat.attribute(idx1)
                val2 = feat.attribute(idx2)

                es_nulo_1 = val1 is None or str(val1) == 'NULL' or str(val1).strip() == ''
                es_nulo_2 = val2 is None or str(val2) == 'NULL' or str(val2).strip() == ''

                # Si detectamos que falta información en al menos uno de los campos seleccionados, iniciamos el rescate espacial
                if es_nulo_1 or es_nulo_2:
                    geom = feat.geometry()
                    if not geom or geom.isEmpty():
                        continue

                    # DIDÁCTICO: list(geom.vertices()) extrae los nodos como una lista plana de puntos QgsPoint.
                    # Esto garantiza compatibilidad absoluta si la capa contiene geometrías MultiLineString complejas.
                    vertices = list(geom.vertices())
                    if len(vertices) < 2:
                        continue
                    
                    # Capturamos los extremos reales: índice 0 (nodo inicial) e índice -1 (nodo final)
                    pt_inicio = vertices[0]
                    pt_fin = vertices[-1]
                    
                    # Forzamos la creación de geometrías tipo punto bidimensionales (2D puras, ignorando datos Z/M)
                    p_inicio = QgsGeometry.fromPointXY(QgsPointXY(pt_inicio.x(), pt_inicio.y()))
                    p_fin = QgsGeometry.fromPointXY(QgsPointXY(pt_fin.x(), pt_fin.y()))

                    # DIDÁCTICO: Creamos cajas de extensión envolventes (Bounding Boxes) sobre los extremos.
                    # Las inflamos con .grow(0.10) para capturar elementos con errores milimétricos de digitalización.
                    caja_inicio = p_inicio.boundingBox()
                    caja_inicio.grow(TOLERANCIA)
                    caja_fin = p_fin.boundingBox()
                    caja_fin.grow(TOLERANCIA)

                    # Consultamos el árbol espacial para aislar los IDs candidatos lejanos y quedarnos solo con el entorno
                    candidatos_ids = set(index_validos.intersects(caja_inicio))
                    candidatos_ids.update(index_validos.intersects(caja_fin))

                    asignado = False
                    # Evaluamos únicamente la distancia real milimétrica del subconjunto de tramos candidatos filtrados
                    for cid in candidatos_ids:
                        tv = tramos_validos_dict[cid]
                        tg = tv.geometry()
                        
                        # Si la distancia del extremo en estudio al tramo con datos es inferior o igual a 10cm:
                        if tg.distance(p_inicio) <= TOLERANCIA or tg.distance(p_fin) <= TOLERANCIA:
                            # Propagamos los identificadores copiando fielmente los atributos originales del donante
                            feat.setAttribute(idx1, tv.attribute(idx1))
                            feat.setAttribute(idx2, tv.attribute(idx2))
                            features_dict[feat_id] = feat  # Salvaguardamos los cambios en el diccionario de memoria
                            asignado = True
                            break  # Salimos del bucle de candidatos: tramo completado, pasamos a evaluar el siguiente huerfano
                    
                    if asignado:
                        cambios_en_iteracion += 1

            feedback.setProgressText(f"Iteración {iteracion}: Se completaron {cambios_en_iteracion} tramos.")
            
            # OPTIMIZACIÓN: Si en una ronda completa del mapa no se rescata ningún tramo nuevo,
            # cancelamos el bucle de forma segura para no desperdiciar ciclos del procesador.
            if cambios_en_iteracion == 0:
                feedback.setProgressText("No se detectaron más tramos conectados que cumplan los criterios. Finalizando bucle.")
                break

        # DIDÁCTICO: Inicializamos el sumidero oficial (Sink) encargado de la generación física del nuevo archivo shapefile.
        # Se le transfiere de manera exacta el esquema original de campos (fields), la proyección espacial (CRS) y el tipo de geometría.
        (sink, dest_id) = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            fields,
            layer.wkbType(),
            layer.sourceCrs()
        )
        
        # Volcado masivo ultrarrápido desde la memoria ram de la máquina hacia el destino físico
        for feat in features_dict.values():
            sink.addFeature(feat, QgsFeatureSink.FastInsert)

        # Devolvemos el ID final para indicar a Procesos que cargue el resultado automáticamente en la leyenda de QGIS
        return {self.OUTPUT: dest_id}
