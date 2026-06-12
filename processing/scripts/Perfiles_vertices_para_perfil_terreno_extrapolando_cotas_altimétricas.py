# -*- coding: utf-8 -*-

## OBLIGATORIO: IMPORTACIÓN DE LIBRERÍAS DE QGIS Y QT
from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (QgsProcessing,
                       QgsProcessingAlgorithm,
                       QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterField,
                       QgsProcessingParameterVectorDestination,
                       QgsWkbTypes,
                       QgsFields, # Modificado para crear un contenedor de campos limpio
                       QgsField,
                       QgsFeature,
                       QgsGeometry,
                       QgsPointXY,
                       QgsSpatialIndex)
import processing

class CrearPerfilTerreno(QgsProcessingAlgorithm):
    
    ## CONSTANTES PARA LOS PARÁMETROS DE LA INTERFAZ
    INPUT_LINEAS = 'INPUT_LINEAS'
    FIELD_ID = 'FIELD_ID'
    INPUT_PUNTOS = 'INPUT_PUNTOS'
    FIELD_COTA = 'FIELD_COTA'
    OUTPUT = 'OUTPUT'

    def tr(self, string):
        return QCoreApplication.translate('Processing', string)

    def createInstance(self):
        return CrearPerfilTerreno()

    def name(self):
        return 'perfiles_crea_bd_perfil_terreno'

    def displayName(self):
        return self.tr('Perfiles – Crea BD perfil terreno sobre tramo abastecimiento')

    def group(self):
        return self.tr('Aquavall - Abastecimiento')

    def groupId(self):
        return 'aquavall_abastecimiento'

    ## AYUDA CONTEXTUAL DEL PANEL LATERAL
    def helpString(self):
        return self.tr("""
        <h3>Perfiles – Crea BD perfil terreno sobre tramo abastecimiento</h3>
        <p>Este algoritmo genera una capa de puntos a partir de los vértices 
        de los tramos de abastecimiento (multilinea), asignando la cota 
        del punto de terreno más cercano.</p>
        
        <b>Pasos del proceso:</b>
        <ol>
        <li>Seleccionar la capa de tramos (líneas) y su ID único.</li>
        <li>Seleccionar la capa de cotas (puntos) y el campo numérico.</li>
        <li>Se vefifica la unicidad de los IDs de los tramos.</li>
        <li>Se extraen vértices y se calcula el vecino más cercano mediante índices espaciales.</li>
        </ol>
        """)

    ## CONFIGURACIÓN DE LA INTERFAZ DE USUARIO (INPUTS/OUTPUTS)
    def initAlgorithm(self, config=None):
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_LINEAS,
                self.tr('Capa de Tramos (Líneas)'),
                [QgsProcessing.TypeVectorLine]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_ID,
                self.tr('Campo Identificador Único de Tramos'),
                parentLayerParameterName=self.INPUT_LINEAS
            )
        )
        
        self.addParameter(
            QgsProcessingParameterFeatureSource(
                self.INPUT_PUNTOS,
                self.tr('Capa de Cotas Altimétricas (Puntos)'),
                [QgsProcessing.TypeVectorPoint]
            )
        )
        
        self.addParameter(
            QgsProcessingParameterField(
                self.FIELD_COTA,
                self.tr('Campo numérico con el valor de la Cota'),
                parentLayerParameterName=self.INPUT_PUNTOS,
                type=QgsProcessingParameterField.Numeric
            )
        )
        
        self.addParameter(
            QgsProcessingParameterVectorDestination(
                self.OUTPUT,
                self.tr('Perfil de Terreno (Puntos)'),
                type=QgsProcessing.TypeVectorPoint
            )
        )

    ## NÚCLEO DE LA EJECUCIÓN DEL ALGORITMO
    def processAlgorithm(self, parameters, context, feedback):
        lineLayer = self.parameterAsVectorLayer(parameters, self.INPUT_LINEAS, context)
        fieldIdName = self.parameterAsString(parameters, self.FIELD_ID, context)
        pointLayer = self.parameterAsVectorLayer(parameters, self.INPUT_PUNTOS, context)
        fieldCotaName = self.parameterAsString(parameters, self.FIELD_COTA, context)
        
        ## BLOQUE 1: VERIFICACIÓN DE IDENTIFICADORES ÚNICOS
        unique_values = set()
        for feat in lineLayer.getFeatures():
            val = feat[fieldIdName]
            if val in unique_values:
                raise Exception(f"¡Error de integridad! El ID '{val}' está repetido en el campo '{fieldIdName}'.")
            unique_values.add(val)
        
        feedback.pushInfo(f"Verificación superada: {len(unique_values)} tramos con ID único garantizado.")

        ## BLOQUE 2: ESTRUCTURACIÓN DE CAMPOS EXCLUSIVOS DE LA CAPA DE SALIDA
        # Se crea un objeto QgsFields vacío para no heredar campos de la capa origen
        new_fields = QgsFields()
        
        # Se añaden única y estrictamente los tres campos requeridos
        new_fields.append(QgsField('ID_TRAMO', QVariant.String))
        new_fields.append(QgsField('COTA_TERR', QVariant.Double, len=10, prec=3))
        new_fields.append(QgsField('DIST_M', QVariant.Double, len=10, prec=3))
        
        sink, dest_id = self.parameterAsSink(
            parameters,
            self.OUTPUT,
            context,
            new_fields,
            QgsWkbTypes.Point, 
            lineLayer.crs()
        )

        ## BLOQUE 3: CONSTRUCCIÓN DE ÍNDICES ESPACIALES
        feedback.pushInfo("Construyendo índice espacial para la capa de puntos...")
        spatial_index = QgsSpatialIndex(pointLayer.getFeatures())
        
        total = 100.0 / lineLayer.featureCount() if lineLayer.featureCount() else 0
        
        ## BLOQUE 4: EXTRACCIÓN DE VÉRTICES Y ENLACE ESPACIAL (SPATIAL JOIN)
        for i, feat in enumerate(lineLayer.getFeatures()):
            if feedback.isCanceled():
                break
                
            line_geom = feat.geometry()
            id_original = feat[fieldIdName]
            
            # Obtener los vértices de la geometría de líneas
            vertices = line_geom.vertices()
            
            for vertex in vertices:
                point_xy = QgsPointXY(vertex.x(), vertex.y())
                vertex_point_geom = QgsGeometry.fromPointXY(point_xy)
                
                # Buscar el ID de la cota (punto) más cercana
                nearest_ids = spatial_index.nearestNeighbor(point_xy, 1)
                
                cota_valor = None
                distancia = None
                
                if nearest_ids:
                    nearest_id = nearest_ids[0]
                    nearest_feat = pointLayer.getFeature(nearest_id)
                    
                    cota_valor = float(nearest_feat[fieldCotaName])
                    distancia = round(vertex_point_geom.distance(nearest_feat.geometry()), 3)
                
                ## BLOQUE 5: GENERACIÓN DEL REGISTRO DE SALIDA SIN ATRIBUTOS HEREDADOS
                new_feat = QgsFeature()
                new_feat.setGeometry(vertex_point_geom)
                
                # Se introducen únicamente los 3 atributos calculados, manteniendo el orden de 'new_fields'
                attrs = [id_original, cota_valor, distancia]
                
                new_feat.setAttributes(attrs)
                sink.addFeature(new_feat)
                
            feedback.setProgress(int(i * total))

        return {self.OUTPUT: dest_id}
