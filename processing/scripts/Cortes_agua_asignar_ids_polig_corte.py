from qgis.processing import alg
from qgis.core import (QgsProcessing, QgsProcessingAlgorithm, 
                       QgsProcessingParameterFeatureSource, 
                       QgsProcessingParameterFeatureSink,
                       QgsProcessingParameterField,
                       QgsProcessingParameterString,
                       QgsFeature, QgsField, QgsGeometry,
                       QgsFeatureSink, QgsPointXY)
from PyQt5.QtCore import QVariant
import random

class ClusterLinesByNodes(QgsProcessingAlgorithm):
    # Definición de constantes de texto para identificar los parámetros en la interfaz
    LINEAS = 'LINEAS'
    PARADAS = 'PARADAS'
    CAMPO_FILTRO = 'CAMPO_FILTRO'
    VALORES_FILTRO = 'VALORES_FILTRO'
    OUTPUT = 'OUTPUT'

    def initAlgorithm(self, config=None):
        #### SECCIÓN 1: CONFIGURACIÓN DE LA INTERFAZ DE USUARIO ####
        
        # Parámetro obligatorio: Capa vectorial que contiene las líneas de la red
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.LINEAS, 'Capa de líneas (Red)', [QgsProcessing.TypeVectorLine]))
        
        # Parámetro OPCIONAL (optional=True): Desplegable dinámico con los campos de la capa de líneas
        self.addParameter(QgsProcessingParameterField(
            self.CAMPO_FILTRO, 'Campo para filtrar registros (Dejar en blanco para procesar TODO)', 
            parentLayerParameterName=self.LINEAS, 
            type=QgsProcessingParameterField.Any,
            optional=True))
            
        # Parámetro OPCIONAL (optional=True): Texto donde el usuario escribe los valores de corte
        self.addParameter(QgsProcessingParameterString(
            self.VALORES_FILTRO, 'Valores permitidos (separados por comas)', 
            defaultValue='', optional=True))

        # Parámetro obligatorio: Capa vectorial de puntos que actúan como fin de sector (válvulas)
        self.addParameter(QgsProcessingParameterFeatureSource(
            self.PARADAS, 'Capa de puntos de parada (Válvulas)', [QgsProcessing.TypeVectorPoint]))
            
        # Parámetro obligatorio: Configuración del sumidero para guardar la nueva capa resultante
        self.addParameter(QgsProcessingParameterFeatureSink(
            self.OUTPUT, 'Capa de salida sectorizada', QgsProcessing.TypeVectorLine))

    def shortHelpString(self):
        #### SECCIÓN DE INSTRUCCIONES BÁSICAS EN FORMATO HTML ####
        return (
            "<h3>Algoritmo de Sectorización de Red de Abastecimiento</h3>"
            "<p>Este script agrupa tramos de tuberías delimitados por válvulas de corte "
            "asignando identificadores únicos (<b>tr_co_id</b>) y códigos de color (<b>tr_color</b>).</p>"
            "<b>Modos de funcionamiento:</b>"
            "<ul>"
            "<li><b>Ejecución Total:</b> Deje el parámetro 'Campo para filtrar' completamente vacío. Se procesará la red entera.</li>"
            "<li><b>Ejecución Filtrada:</b> Seleccione un campo y escriba los valores válidos separados por comas. "
            "Los tramos que no coincidan se aislarán, no propagarán conectividad y recibirán valores NULL en sus identificadores.</li>"
            "</ul>"
            "<p><i>Nota: El texto introducido para el filtrado distingue entre mayúsculas y minúsculas (Sensible a Case).</i></p>"
        )

    def processAlgorithm(self, parameters, context, feedback):
        #### SECCIÓN 2: CARGA Y EVALUACIÓN PRELIMINAR DE PARÁMETROS ####
        
        # Convertimos las referencias de la interfaz en fuentes de datos usables
        lyr_lineas = self.parameterAsSource(parameters, self.LINEAS, context)
        lyr_paradas = self.parameterAsSource(parameters, self.PARADAS, context)
        
        # Extraemos la información de filtrado como cadenas de texto planos
        nombre_campo = self.parameterAsString(parameters, self.CAMPO_FILTRO, context)
        string_valores = self.parameterAsString(parameters, self.VALORES_FILTRO, context)
        
        # CONTROL REGLA CLAVE: Evaluamos si el usuario ha seleccionado un campo válido para filtrar
        # Si 'nombre_campo' tiene texto, la variable booleana será True; si está vacío, False
        aplicar_filtro = True if nombre_campo else False
        
        # Inicializamos variables por defecto para el filtrado
        valores_validos = set()
        idx_campo = -1
        
        # Si se requiere filtrar, preparamos las variables con su respectivo índice y limpieza de espacios
        if aplicar_filtro:
            valores_validos = {v.strip() for v in string_valores.split(',') if v.strip()}
            idx_campo = lyr_lineas.fields().indexOf(nombre_campo)
        
        # Extraemos las coordenadas geométricas de los puntos de parada en un conjunto optimizado en memoria
        puntos_parada = {QgsPointXY(f.geometry().asPoint()) for f in lyr_paradas.getFeatures()}
        
        # Inicializamos los contenedores principales de la red
        adyacencia = {}       # Grafo: clave=Nodo(PuntoXY), valor=Lista de IDs de tramos que tocan ese nodo
        todos_los_tramos = {} # Almacén: clave=ID de la entidad, valor=Objeto entidad completo (Feature)
        tramos_excluidos = set() # Registro para guardar los IDs de las líneas que no pasan el filtro del usuario
        
        #### SECCIÓN 3: EXTRACCIÓN DE LA RED Y CONSTRUCCIÓN DEL GRAFO TOPOLÓGICO ####
        
        for f in lyr_lineas.getFeatures():
            todos_los_tramos[f.id()] = f # Guardamos la entidad en nuestro almacén general
            
            # FILTRADO DINÁMICO: Si el filtro está activado, comprobamos si la entidad debe ser excluida
            if aplicar_filtro:
                val_atributo = str(f.attributes()[idx_campo]) if idx_campo != -1 else ""
                if val_atributo not in valores_validos:
                    tramos_excluidos.add(f.id()) # Se almacena en la lista negra
                    continue # Saltar a la siguiente iteración; no se conecta topológicamente
                
            # Tratamiento geométrico para extraer los extremos reales de la tubería
            geom = f.geometry()
            partes = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
            
            for linea in partes:
                # Obtenemos los dos nodos extremos (inicial y final) como objetos precisos QgsPointXY
                nodos_extremos = [QgsPointXY(linea[0]), QgsPointXY(linea[-1])]
                for p in nodos_extremos:
                    if p not in adyacencia: 
                        adyacencia[p] = []
                    # Añadimos este ID de línea al nodo correspondiente para mapear la conectividad física
                    adyacencia[p].append(f.id())

        #### SECCIÓN 4: CREACIÓN Y ESTRUCTURA DE LA NUEVA CAPA VECTORIAL ####
        
        # Clonamos la tabla de atributos original de la capa de líneas de entrada
        fields = lyr_lineas.fields()
        # Añadimos nuestras dos nuevas columnas dedicadas al análisis de sectorización
        fields.append(QgsField("tr_co_id", QVariant.Int))
        fields.append(QgsField("tr_color", QVariant.Int))
        
        # Instanciamos el sumidero (sink) final clonando tipos de geometría y sistemas de coordenadas (CRS)
        (sink, dest_id) = self.parameterAsSink(
            parameters, self.OUTPUT, context, fields, 
            lyr_lineas.wkbType(), lyr_lineas.sourceCrs())

        #### SECCIÓN 5: ALGORITMO BFS (BÚSQUEDA EN ANCHURA) PARA PROPAGACIÓN DE SECTORES ####
        
        tramos_procesados = set() # Control de elementos ya analizados y resueltos
        grupo_id = 1             # Contador correlativo para asignar IDs de sectores únicos

        for t_id in todos_los_tramos:
            # Control de exclusión: Si ya pertenece a un sector o está excluido por filtro, ignorar inicio de red
            if t_id in tramos_procesados or t_id in tramos_excluidos:
                continue
            
            # Generamos un número aleatorio del 0 al 9 que representará el color de la zona en QGIS
            color_sector = random.randint(0, 9)
            cola_tramos = [t_id]  # Inicializamos la cola de propagación con el tramo raíz actual
            grupo_actual = set()   # Conjunto para agrupar todas las líneas que componen este sector aislado
            
            while cola_tramos:
                actual_id = cola_tramos.pop(0) # Extraemos el primer elemento disponible de la cola
                if actual_id in tramos_procesados:
                    continue
                
                tramos_procesados.add(actual_id)
                grupo_actual.add(actual_id)
                f = todos_los_tramos[actual_id]
                
                geom = f.geometry()
                partes = geom.asMultiPolyline() if geom.isMultipart() else [geom.asPolyline()]
                
                for linea in partes:
                    nodos_linea = [QgsPointXY(linea[0]), QgsPointXY(linea[-1])]
                    for nodo in nodos_linea:
                        # CRITERIO DE DETENCIÓN: Si el nodo NO coincide con una válvula, la red continúa viva
                        if nodo not in puntos_parada:
                            # Exploramos todos los tramos vecinos conectados físicamente a este mismo nodo
                            for vecino_id in adyacencia.get(nodo, []):
                                # El vecino avanza si no ha sido resuelto y si tampoco está excluido por filtros
                                if vecino_id not in tramos_procesados and vecino_id not in tramos_excluidos:
                                    cola_tramos.append(vecino_id)

            #### SECCIÓN 6: ESCRITURA EN DISCO DE LOS TRAMOS SECTORIZADOS ####
            
            for fid in grupo_actual:
                original_feat = todos_los_tramos[fid]
                new_feat = QgsFeature(fields)
                new_feat.setGeometry(original_feat.geometry()) # Heredamos geometría original
                
                attrs = original_feat.attributes()
                attrs.append(grupo_id)     # Inyectamos el ID numérico del sector
                attrs.append(color_sector) # Inyectamos el código estético de color
                
                new_feat.setAttributes(attrs)
                sink.addFeature(new_feat, QgsFeatureSink.FastInsert) # Volcado rápido al sumidero de datos
            
            grupo_id += 1 # Incrementamos el identificador numérico para el siguiente sector geográfico

        #### SECCIÓN 7: ESCRITURA EN DISCO DE ELEMENTOS EXCLUIDOS (ASIGNACIÓN NULL) ####
        
        # Este bloque se ejecuta siempre. Si la ejecución fue total, 'tramos_excluidos' estará vacío y se omitirá de forma limpia.
        for fid in tramos_excluidos:
            original_feat = todos_los_tramos[fid]
            new_feat = QgsFeature(fields)
            new_feat.setGeometry(original_feat.geometry()) # Conservamos geometría intacta
            
            attrs = original_feat.attributes()
            attrs.append(None) # Almacenamos un valor NULL de base de datos para tr_co_id
            attrs.append(None) # Almacenamos un valor NULL de base de datos para tr_color
            
            new_feat.setAttributes(attrs)
            sink.addFeature(new_feat, QgsFeatureSink.FastInsert)

        # Retornamos la referencia técnica de la capa creada para que QGIS la cargue automáticamente en la vista del mapa
        return {self.OUTPUT: dest_id}

    # Métodos estáticos obligatorios de metadatos del algoritmo para el árbol de Procesos de QGIS
    def name(self): return 'cortes_agua_asignar_ids_polig_corte'
    def displayName(self): return 'Cortes agua - Asignar identificadores de poligonos de corte'
    def group(self): return 'Aquavall - Abastecimiento'
    def groupId(self): return 'aquavall_abastecimiento'
    def createInstance(self): return ClusterLinesByNodes()
